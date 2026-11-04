"""Crawl PDF và mẫu đơn cho các thủ tục đang ở trạng thái DRAFT.

Bản tối ưu cho laptop RAM 4GB:
  * Chỉ 1 Chrome duy nhất (Chrome là thứ ngốn RAM nhất, không phải worker).
  * Bỏ WebDriverWait 25s cho link ``a.url[href]`` (mất ~25s/thủ tục nếu không có).
  * Poll file tải về theo backoff 40ms thay vì 500ms cố định mỗi vòng.
  * Chặn ảnh/font/analytics + ``page_load_strategy="eager"`` -> trang nhẹ hơn.
  * Upload S3 chạy song song trong thread pool (I/O bound, RAM không đáng kể).
  * Đọc DB theo lô (keyset pagination) + SAVEPOINT + commit mỗi ``--commit-every``.
  * Có resume (``--resume``) để chạy tiếp sau khi tắt máy / hết điện.

Ví dụ:
    python scripts/ingestion/seed_database.py --limit 10 --verbose
    python scripts/ingestion/seed_database.py --code 1.001193 --no-headless
    python scripts/ingestion/seed_database.py --code 1.001193 1.002345 1.003456
    python scripts/ingestion/seed_database.py --resume --commit-every 20
"""

from __future__ import annotations

import argparse
import base64
import logging
import mimetypes
import os
import re
import sys
import tempfile
import time
import unicodedata
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from urllib.parse import quote

import boto3
from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from sqlalchemy import func
from sqlalchemy.orm import selectinload

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.basis import Basis  # noqa: E402
from app.models.component import Component  # noqa: E402
from app.models.component_document import ComponentDocument  # noqa: E402
from app.models.method import Method  # noqa: E402
from app.models.procedure import Procedure  # noqa: E402
from app.models.procedure_group import ProcedureGroup, ProcedureGroupStatus  # noqa: E402
from scripts.ingestion.parsing import parse_pdf  # noqa: E402

load_dotenv(ROOT / ".env")
LOGGER = logging.getLogger("seed_database")
SEARCH_URL = (
    "https://dichvucong.gov.vn/dvc-ket-qua-thu-tuc?keyword={code}"
)
DEFAULT_DRIVER_PATH = r"D:\chromedriver-win64\chromedriver.exe"
RESULT_SELECTOR = "a.text-lg.block"
REFERENCE_SELECTOR = "a.url[href]"
PARTIAL_SUFFIXES = (".crdownload", ".tmp", ".part")


@dataclass
class ScrapedProcedure:
    page_url: str
    detail_pdf: Path
    form_files: list[Path]
    form_links: list[str]


def normalise(value: str) -> str:
    value = unicodedata.normalize("NFD", value or "")
    return "".join(c for c in value if unicodedata.category(c) != "Mn").lower()


def safe_name(value: str, default: str = "file") -> str:
    value = Path(value).name
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._") or default


# --------------------------------------------------------------------------- #
# Selenium
# --------------------------------------------------------------------------- #
def make_driver(download_dir: Path, headless: bool, driver_path: str | None,
                block_heavy: bool = True):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    for argument in (
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--window-size=1366,900",
        "--lang=vi-VN",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-sync",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        "--disable-features=Translate,CalculateNativeWinOcclusion",
        "--blink-settings=imagesEnabled=false",
        "--disk-cache-size=67108864",
    ):
        options.add_argument(argument)
    # Không chờ ảnh/hình tải xong mới coi là "đã load" -> mỗi lần rẽ trang nhanh hơn.
    options.page_load_strategy = "eager"
    options.add_experimental_option("prefs", {
        "download.default_directory": str(download_dir.resolve()),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,
        "safebrowsing.enabled": True,
    })
    service = Service(driver_path) if driver_path else Service()
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(40)
    driver.execute_cdp_cmd("Page.setDownloadBehavior", {
        "behavior": "allow", "downloadPath": str(download_dir.resolve())
    })
    if block_heavy:
        # Chỉ chặn tài nguyên không ảnh hưởng tới DOM/nút tải.
        driver.execute_cdp_cmd("Network.enable", {})
        try:
            driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": [
                "*google-analytics.com*", "*googletagmanager.com*",
                "*googlesyndication*", "*doubleclick.net*", "*facebook.net*",
                "*hotjar*", "*clarity.ms*", "*.woff", "*.woff2", "*.ttf",
            ]})
        except WebDriverException:
            LOGGER.debug("Không đặt được blocked URLs")
    return driver


def goto(driver, url: str) -> None:
    """``driver.get`` có nuốt TimeoutException (trang chậm không làm chết vòng lặp)."""
    try:
        driver.get(url)
    except TimeoutException:
        LOGGER.debug("page_load_timeout (vẫn tiếp tục): %s", url)


def wait_for_download(directory: Path, before: set[str], timeout: float = 45.0) -> Path | None:
    """Poll thích nghi 40ms -> 350ms, thay vì 500ms cố định mỗi vòng.

    ``os.listdir`` rẻ hơn ``Path.iterdir()`` + ``stat()`` trên từng file.
    """
    deadline = time.monotonic() + timeout
    delay = 0.04
    while time.monotonic() < deadline:
        names = os.listdir(directory)
        if any(name.endswith(PARTIAL_SUFFIXES) for name in names):
            time.sleep(delay)
            delay = min(delay * 1.7, 0.35)
            continue
        new_names = [name for name in names if name not in before]
        if new_names:
            candidates = [directory / name for name in new_names]
            path = max(candidates, key=lambda item: item.stat().st_mtime)
            if path.stat().st_size:
                return path
        time.sleep(delay)
        delay = min(delay * 1.7, 0.35)
    return None


def click_download(driver, element, directory: Path) -> Path | None:
    before = set(os.listdir(directory))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
    driver.execute_script("arguments[0].click();", element)
    return wait_for_download(directory, before)


def open_first_search_result(driver, code: str, timeout: int) -> str:
    """Mở URL tìm kiếm theo mã rồi truy cập ``href`` của kết quả đầu tiên."""
    wait = WebDriverWait(driver, timeout)
    search_url = SEARCH_URL.format(code=quote(code))
    goto(driver, search_url)

    try:
        result = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, RESULT_SELECTOR))
        )
        result_url = result.get_attribute("href")
        if not result_url:
            raise RuntimeError(f"Kết quả {code} không có đường dẫn chi tiết")
        goto(driver, result_url)
        wait.until(lambda d: d.current_url != search_url and d.execute_script(
            "return document.readyState") == "complete")
        LOGGER.debug("Đã mở kết quả %s: %s", code, result_url)
        return result_url
    except TimeoutException as exc:
        raise RuntimeError(
            f"Không tìm thấy kết quả cho mã thủ tục {code} tại {search_url}"
        ) from exc


def open_reference_page(driver, timeout: int, probe: float = 1.0) -> str:
    """Trang kết quả có thể chứa link sang trang dữ liệu chi tiết thật.

    Khác bản cũ: chỉ chờ tối đa ``probe`` giây. Bản cũ dùng ``timeout`` (25s)
    nên mỗi thủ tục không có link này mất thêm 25 giây vô ích.
    """
    try:
        reference = WebDriverWait(driver, probe).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, REFERENCE_SELECTOR)))
        href = reference.get_attribute("href")
        if href:
            goto(driver, href)
    except TimeoutException:
        pass
    return driver.current_url


def dump_xhr(driver) -> list[str]:
    """Liệt kê request XHR/fetch của trang hiện tại (để tìm API thay Selenium)."""
    return driver.execute_script("""
        return performance.getEntriesByType('resource')
            .map(e => e.name)
            .filter(u => u.includes('/api/') || u.includes('graphql'));
    """)


# --------------------------------------------------------------------------- #
# Tải file
# --------------------------------------------------------------------------- #
def download_forms(driver, directory: Path, max_forms: int | None = None
                   ) -> tuple[list[Path], list[str]]:
    files: list[Path] = []
    links: list[str] = []
    seen: set[str] = set()
    directory.mkdir(parents=True, exist_ok=True)

    sections = driver.find_elements(
        By.XPATH,
        '//h4[contains(normalize-space(.), "Thành phần hồ sơ")]/parent::div'
    )
    if not sections:
        LOGGER.info("Không thấy khu vực Thành phần hồ sơ")
        return files, links

    for section in sections:
        form_sections = section.find_elements(
            By.XPATH,
            './/span[normalize-space(.)="Mẫu đơn, tờ khai:"]/parent::div'
        )

        for table in section.find_elements(By.CSS_SELECTOR, "table"):
            headers = table.find_elements(By.CSS_SELECTOR, "thead th")
            labels = [normalise(header.text) for header in headers]
            indexes = [
                index for index, label in enumerate(labels)
                if "mau don" in label or "to khai" in label
            ]
            if not indexes:
                continue
            for row in table.find_elements(By.CSS_SELECTOR, "tbody tr"):
                cells = row.find_elements(By.TAG_NAME, "td")
                for index in indexes:
                    if index < len(cells):
                        form_sections.append(cells[index])

    LOGGER.info("Tìm thấy %d khu vực mẫu đơn", len(form_sections))

    for form_section in form_sections:
        containers = form_section.find_elements(
            By.XPATH,
            './/div[contains(@class, "justify-between")][.//button]'
        )
        for container in containers:
            if max_forms is not None and len(files) >= max_forms:
                LOGGER.info("Đã đạt giới hạn %d mẫu đơn, bỏ qua phần còn lại", max_forms)
                return files, links

            filename_elements = container.find_elements(By.CSS_SELECTOR, "span.break-all")
            buttons = container.find_elements(By.TAG_NAME, "button")
            if not filename_elements or not buttons:
                continue

            filename = filename_elements[0].text.strip()
            if not filename or filename in seen:
                continue
            seen.add(filename)

            LOGGER.info("Đang tải mẫu đơn: %s", filename)
            downloaded = click_download(driver, buttons[0], directory)
            if downloaded:
                files.append(downloaded)
                LOGGER.info("Tải thành công: %s", downloaded)
            else:
                LOGGER.warning("Không tải được: %s", filename)

    return files, links


def download_detail_pdf(driver, directory: Path, code: str) -> Path:
    for element in driver.find_elements(By.CSS_SELECTOR, "button:has(svg.text-red-500)"):
        if element.is_displayed():
            downloaded = click_download(driver, element, directory)
            if downloaded and downloaded.suffix.lower() == ".pdf":
                return downloaded

    # Fallback ổn định khi nút tải của cổng thay đổi: in chính trang chi tiết ra PDF.
    payload = driver.execute_cdp_cmd("Page.printToPDF", {
        "printBackground": True, "preferCSSPageSize": True
    })
    path = directory / f"chi-tiet-thu-tuc-{safe_name(code)}.pdf"
    path.write_bytes(base64.b64decode(payload["data"]))
    return path


def scrape_procedure(driver, code: str, directory: Path, timeout: int,
                     max_forms: int | None = None) -> ScrapedProcedure:
    open_first_search_result(driver, code, timeout)
    page_url = open_reference_page(driver, timeout)
    form_files, form_links = download_forms(driver, directory, max_forms)
    detail_pdf = download_detail_pdf(driver, directory, code)
    return ScrapedProcedure(page_url, detail_pdf, form_files, form_links)


# --------------------------------------------------------------------------- #
# S3
# --------------------------------------------------------------------------- #
def make_s3_client():
    bucket = os.getenv("AWS_BUCKET")
    region = os.getenv("AWS_DEFAULT_REGION")
    if not bucket or not region:
        raise RuntimeError("Thiếu AWS_BUCKET hoặc AWS_DEFAULT_REGION/AWS_REGION")
    client = boto3.client(
        "s3", aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN"), region_name=region)
    return client, bucket, region


def upload_file(client, bucket: str, region: str, path: Path, key: str) -> str:
    client.upload_file(str(path), bucket, key, ExtraArgs={
        "ContentType": mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    })
    return f"https://{bucket}.s3.{region}.amazonaws.com/{quote(key, safe='/')}"


# --------------------------------------------------------------------------- #
# ORM
# --------------------------------------------------------------------------- #
def latest_version(group: ProcedureGroup) -> Procedure:
    if group.versions:
        return max(group.versions, key=lambda item: item.created_at)
    version = Procedure(procedure_id=group.id, name=group.name)
    group.versions.append(version)
    return version


def apply_parsed_data(version: Procedure, parsed: dict) -> None:
    """Ghi kết quả ``parse_pdf`` vào phiên bản thủ tục hiện tại."""
    data = dict(parsed)
    components = data.pop("components", []) or []
    methods = data.pop("methods", []) or []
    bases = data.pop("bases", []) or []
    data.pop("code", None)

    procedure_fields = {column.name for column in Procedure.__table__.columns}
    ignored_fields = {
        "id",
        "procedure_id",
        "created_at",
        "updated_at",
        "page_url",
        "document_url",
        "form_urls",
    }
    for key, value in data.items():
        if key in procedure_fields and key not in ignored_fields:
            if key == "name" and not value:
                continue
            setattr(version, key, value)

    version.methods = [Method(**item) for item in methods]
    version.bases = [Basis(**item) for item in bases]
    version.components = []
    for item in components:
        component_data = dict(item)
        documents = component_data.pop("documents", []) or []
        component = Component(**component_data)
        component.documents = [ComponentDocument(**document) for document in documents]
        version.components.append(component)


# --------------------------------------------------------------------------- #
# DB: đọc theo lô, không nạp 7000 group vào RAM
# --------------------------------------------------------------------------- #
def count_draft(db, codes: list[str] | None) -> int:
    query = db.query(func.count(ProcedureGroup.id)).filter(
        ProcedureGroup.status == ProcedureGroupStatus.DRAFT)
    if codes:
        query = query.filter(ProcedureGroup.code.in_(codes))
    return int(query.scalar() or 0)


def iter_draft(db, codes: list[str] | None, limit: int | None,
               chunk: int = 100) -> Iterator[tuple[int, str, str]]:
    """Keyset pagination theo ``(created_at, id)``.

    Trả về tuple thường (không phải ORM object) nên commit giữa các lô không
    làm hỏng con trỏ, và RAM chỉ giữ ``chunk`` dòng mỗi lần.
    """
    fetched = 0
    last_created = None
    last_id = None
    while True:
        size = chunk if limit is None else min(chunk, limit - fetched)
        if size <= 0:
            return
        query = db.query(
            ProcedureGroup.id,
            ProcedureGroup.code,
            ProcedureGroup.name,
            ProcedureGroup.created_at,
        ).filter(ProcedureGroup.status == ProcedureGroupStatus.DRAFT)
        if codes:
            query = query.filter(ProcedureGroup.code.in_(codes))
        if last_created is not None:
            query = query.filter(
                (ProcedureGroup.created_at > last_created)
                | ((ProcedureGroup.created_at == last_created)
                   & (ProcedureGroup.id > last_id))
            )
        rows = (query.order_by(ProcedureGroup.created_at.asc(), ProcedureGroup.id.asc())
                     .limit(size).all())
        if not rows:
            return
        for row in rows:
            yield row.id, row.code, row.name
        fetched += len(rows)
        last_created, last_id = rows[-1].created_at, rows[-1].id


def load_done(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()}


def cleanup(directory: Path) -> None:
    for path in directory.iterdir():
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                LOGGER.warning("Không xoá được file tạm %s", path)


def human(seconds: float) -> str:
    seconds = int(max(seconds, 0))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m{secs:02d}s"


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #
def run(args: argparse.Namespace) -> int:
    s3, bucket, region = make_s3_client()

    if args.parser != "auto":
        os.environ["PDF_BACKEND"] = args.parser

    temp_root = Path(args.temp_dir)
    temp_root.mkdir(parents=True, exist_ok=True)
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    done_file = state_dir / "done.txt"
    done = load_done(done_file) if args.resume else set()
    resume_fh = done_file.open("a", encoding="utf-8") if args.resume else None

    succeeded = failed = skipped = 0
    pending = 0
    batch_codes: list[str] = []
    recent: deque[float] = deque(maxlen=30)
    started_all = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="dvc-seed-", dir=temp_root) as temp_name:
        directory = Path(temp_name)
        driver = make_driver(directory, args.headless, args.driver_path, not args.no_images)
        uploads = ThreadPoolExecutor(max_workers=args.upload_workers)
        try:
            with SessionLocal() as db:
                total = count_draft(db, args.code)
                LOGGER.info("Tìm thấy %d thủ tục DRAFT", total)
                position = 0

                for group_id, group_code, group_name in iter_draft(
                        db, args.code, args.limit, args.chunk):
                    position += 1
                    if group_code in done:
                        skipped += 1
                        continue

                    LOGGER.info("[%d/%d] %s - %s", position, total, group_code, group_name)
                    t0 = time.monotonic()
                    try:
                        # SAVEPOINT: lỗi của thủ tục này không kéo theo cả lô.
                        with db.begin_nested():
                            group = (
                                db.query(ProcedureGroup)
                                .options(selectinload(ProcedureGroup.versions))
                                .filter(ProcedureGroup.id == group_id)
                                .one()
                            )
                            scraped = scrape_procedure(
                                driver, group_code, directory, args.timeout, args.max_forms)
                            t_crawl = time.monotonic()

                            parsed_result = parse_pdf(scraped.detail_pdf, args.parser)
                            if "procedure" not in parsed_result:
                                raise ValueError(
                                    f"Parser không trả về procedure cho mã {group_code}")
                            parsed_procedure = parsed_result["procedure"]
                            parsed_code = parsed_procedure.get("code")
                            if parsed_code and str(parsed_code).strip() != group_code:
                                raise ValueError(
                                    f"Mã trong tài liệu ({parsed_code}) không khớp "
                                    f"mã thủ tục ({group_code})")
                            t_parse = time.monotonic()

                            prefix = f"procedures/{safe_name(group_code)}"
                            detail_key = (
                                f"{prefix}/detail/"
                                f"{safe_name(scraped.detail_pdf.name, 'detail.pdf')}"
                            )
                            futures = [uploads.submit(
                                upload_file, s3, bucket, region,
                                scraped.detail_pdf, detail_key)]
                            for number, form_path in enumerate(scraped.form_files, 1):
                                futures.append(uploads.submit(
                                    upload_file, s3, bucket, region, form_path,
                                    f"{prefix}/forms/{number:02d}-{safe_name(form_path.name)}"))

                            document_url = futures[0].result()
                            form_urls = list(dict.fromkeys(
                                [*scraped.form_links, *(f.result() for f in futures[1:])]))
                            t_upload = time.monotonic()

                            version = latest_version(group)
                            apply_parsed_data(version, parsed_procedure)
                            version.page_url = scraped.page_url
                            version.document_url = document_url
                            version.form_urls = list(dict.fromkeys(form_urls))
                            # Hai trường tóm tắt này cũng tồn tại ở bảng procedures.
                            group.page_url = scraped.page_url
                            group.document_url = document_url
                            group.status = ProcedureGroupStatus.ARCHIVED

                        succeeded += 1
                        pending += 1
                        batch_codes.append(group_code)
                        LOGGER.debug(
                            "timing code=%s crawl=%.1fs parse=%.1fs parse+upload=%.1fs total=%.1fs",
                            group_code, t_crawl - t0, t_parse - t_crawl,
                            t_upload - t_parse, time.monotonic() - t0)

                        if pending >= args.commit_every:
                            db.commit()
                            pending = 0
                            if resume_fh:
                                resume_fh.write("\n".join(batch_codes) + "\n")
                                resume_fh.flush()
                            batch_codes.clear()
                    except Exception:
                        failed += 1
                        LOGGER.exception("Xử lý thất bại thủ tục %s", group_code)
                    finally:
                        cleanup(directory)
                        elapsed = time.monotonic() - t0
                        recent.append(elapsed)
                        if recent:
                            average = sum(recent) / len(recent)
                            left = max(total - position, 0)
                            LOGGER.info(
                                "  → %.1fs/thủ tục | còn ~%s | đã chạy %s",
                                average, human(average * left),
                                human(time.monotonic() - started_all))

                db.commit()
                if resume_fh and batch_codes:
                    resume_fh.write("\n".join(batch_codes) + "\n")
                    resume_fh.flush()
        finally:
            uploads.shutdown(wait=True)
            driver.quit()
            if resume_fh:
                resume_fh.close()

    LOGGER.info("Hoàn tất: %d thành công, %d thất bại, %d bỏ qua (đã có) sau %s",
                succeeded, failed, skipped, human(time.monotonic() - started_all))
    return 1 if failed else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl tài liệu cho ProcedureGroup DRAFT")
    parser.add_argument(
        "--code", nargs="+", metavar="CODE",
        help="Chỉ xử lý một hoặc nhiều mã thủ tục")
    parser.add_argument("--limit", type=int, help="Số thủ tục tối đa")
    parser.add_argument("--timeout", type=int, default=25, help="Timeout Selenium (giây)")
    parser.add_argument(
        "--driver-path", default=DEFAULT_DRIVER_PATH,
        help=f"ChromeDriver tương thích (mặc định: {DEFAULT_DRIVER_PATH})")
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--verbose", action="store_true")
    # --- các cờ mới ---
    parser.add_argument("--parser", choices=("auto", "mupdf", "plumber"), default="auto",
                        help="Backend đọc PDF (auto = PyMuPDF nếu có)")
    parser.add_argument("--commit-every", type=int, default=20,
                        help="Commit mỗi N thủ tục (1 = hành vi cũ)")
    parser.add_argument("--chunk", type=int, default=100,
                        help="Số dòng lấy từ DB mỗi lô")
    parser.add_argument("--upload-workers", type=int, default=4,
                        help="Số luồng upload S3 (I/O bound, 4-6 là đủ)")
    parser.add_argument("--max-forms", type=int, default=None,
                        help="Giới hạn số mẫu đơn tải mỗi thủ tục")
    parser.add_argument("--resume", action="store_true",
                        help="Bỏ qua các mã đã xử lý (state/done.txt)")
    parser.add_argument("--state-dir", default=str(ROOT / "data" / "ingest_state"),
                        help="Nơi lưu tiến độ")
    parser.add_argument("--temp-dir", default=r"E:\temp",
                        help="Thư mục tạm cho file tải về")
    parser.add_argument("--no-images", action="store_true",
                        help="Tắt ảnh (mặc định bật)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        return run(args)
    except (RuntimeError, WebDriverException):
        LOGGER.exception("Không thể khởi tạo tiến trình seed")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
