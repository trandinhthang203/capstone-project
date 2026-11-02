"""Crawl PDF và mẫu đơn cho các thủ tục đang ở trạng thái DRAFT.

Ví dụ:
    python scripts/ingestion/seed_database.py --limit 10
    python scripts/ingestion/seed_database.py --code 1.001193 --no-headless
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
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urljoin

import boto3
from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException, StaleElementReferenceException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.procedure import Procedure  # noqa: E402
from app.models.procedure_group import ProcedureGroup, ProcedureGroupStatus  # noqa: E402

load_dotenv(ROOT / ".env")
LOGGER = logging.getLogger("seed_database")
SEARCH_URL = (
    "https://dichvucong.gov.vn/dvc-ket-qua-thu-tuc?keyword={code}"
)
DEFAULT_DRIVER_PATH = r"D:\chromedriver-win64\chromedriver.exe"
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


def make_driver(download_dir: Path, headless: bool, driver_path: str | None):
    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    for argument in ("--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                     "--window-size=1920,1080", "--lang=vi-VN"):
        options.add_argument(argument)
    options.add_experimental_option("prefs", {
        "download.default_directory": str(download_dir.resolve()),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,
        "safebrowsing.enabled": True,
    })
    service = Service(driver_path) if driver_path else Service()
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_cdp_cmd("Page.setDownloadBehavior", {
        "behavior": "allow", "downloadPath": str(download_dir.resolve())
    })
    return driver


def wait_for_download(directory: Path, before: set[Path], timeout: int = 45) -> Path | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        files = {p for p in directory.iterdir() if p.is_file()}
        pending = [p for p in files if p.name.endswith(PARTIAL_SUFFIXES)]
        completed = [p for p in files - before
                     if not p.name.endswith(PARTIAL_SUFFIXES) and p.stat().st_size]
        if completed and not pending:
            return max(completed, key=lambda p: p.stat().st_mtime)
        time.sleep(0.5)
    return None


def click_download(driver, element, directory: Path) -> Path | None:
    before = {p for p in directory.iterdir() if p.is_file()}
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
    driver.execute_script("arguments[0].click();", element)
    return wait_for_download(directory, before)


def open_first_search_result(driver, code: str, timeout: int) -> str:
    """Mở URL tìm kiếm theo mã rồi truy cập ``href`` của kết quả đầu tiên."""
    wait = WebDriverWait(driver, timeout)
    search_url = SEARCH_URL.format(code=quote(code))
    driver.get(search_url)

    # Kết quả tìm kiếm hiện tại dẫn tới route /thu-tuc-hanh-chinh/{id}.
    result_selector = "a.text-lg.block"
    try:
        result = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, result_selector))
        )
        result_url = result.get_attribute("href")
        if not result_url:
            raise RuntimeError(f"Kết quả {code} không có đường dẫn chi tiết")
        driver.get(result_url)
        wait.until(lambda d: d.current_url != search_url and d.execute_script(
            "return document.readyState") == "complete")
        LOGGER.debug("Đã mở kết quả %s: %s", code, result_url)
        return result_url
    except TimeoutException as exc:
        raise RuntimeError(
            f"Không tìm thấy kết quả cho mã thủ tục {code} tại {search_url}"
        ) from exc


def open_reference_page(driver, timeout: int) -> str:
    """Trang kết quả có thể chứa link sang trang dữ liệu chi tiết thật."""
    try:
        reference = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a.url[href]")))
        if reference.get_attribute("href"):
            driver.get(reference.get_attribute("href"))
    except TimeoutException:
        pass
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "body")))
    return driver.current_url

from pathlib import Path
from urllib.parse import urljoin

from selenium.webdriver.common.by import By


def download_forms(driver, directory: Path) -> tuple[list[Path], list[str]]:
    files, links, seen = [], [], set()

    directory.mkdir(parents=True, exist_ok=True)

    # Chỉ tìm trong khu vực Thành phần hồ sơ
    sections = driver.find_elements(
        By.XPATH,
        '//h4[contains(normalize-space(.), "Thành phần hồ sơ")]/parent::div'
    )

    for section in sections:

        # KIỂU 1: HTML sử dụng div/span
        form_sections = section.find_elements(
            By.XPATH,
            './/span[normalize-space(.)="Mẫu đơn, tờ khai:"]/parent::div'
        )

        # KIỂU 2: HTML sử dụng table
        for table in section.find_elements(By.CSS_SELECTOR, "table"):
            headers = table.find_elements(By.CSS_SELECTOR, "thead th")

            indexes = [
                i for i, header in enumerate(headers)
                if "mau don" in normalise(header.text)
                or "to khai" in normalise(header.text)
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
            # Tìm các file trong khu vực mẫu đơn
            file_containers = form_section.find_elements(
                By.XPATH,
                './/div[contains(@class, "justify-between")][.//button]'
            )

            for container in file_containers:
                filename_elements = container.find_elements(
                    By.CSS_SELECTOR,
                    "span.break-all"
                )

                buttons = container.find_elements(
                    By.TAG_NAME, "button"
                )

                if not filename_elements or not buttons:
                    continue

                filename = filename_elements[0].text.strip()

                if not filename or filename in seen:
                    continue

                seen.add(filename)

                LOGGER.info("Đang tải mẫu đơn: %s", filename)

                downloaded = click_download(
                    driver,
                    buttons[0],
                    directory
                )

                if downloaded:
                    files.append(downloaded)
                    LOGGER.info("Tải thành công: %s", downloaded)
                else:
                    LOGGER.warning("Không tải được: %s", filename)

    return files, links


def download_detail_pdf(driver, directory: Path, code: str) -> Path:
    candidates = driver.find_elements(By.XPATH,
        "//*[self::a or self::button or self::span]["
        "contains(translate(normalize-space(.),'TẢI VỀ','tai ve'),'tai ve') or "
        "contains(@onclick,'downloadTTHC') or contains(@onclick,'downloadTthc') or "
        "contains(@class,'download')]"
    )
    for element in candidates:
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


def scrape_procedure(driver, code: str, directory: Path, timeout: int) -> ScrapedProcedure:
    open_first_search_result(driver, code, timeout)
    page_url = open_reference_page(driver, timeout)
    form_files, form_links = download_forms(driver, directory)
    detail_pdf = download_detail_pdf(driver, directory, code)
    return ScrapedProcedure(page_url, detail_pdf, form_files, form_links)


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


def latest_version(group: ProcedureGroup) -> Procedure:
    if group.versions:
        return max(group.versions, key=lambda item: item.created_at)
    version = Procedure(procedure_id=group.id, name=group.name)
    group.versions.append(version)
    return version


def run(args: argparse.Namespace) -> int:
    s3, bucket, region = make_s3_client()
    succeeded = failed = 0
    with tempfile.TemporaryDirectory(prefix="dvc-seed-") as temp_name:
        directory = Path(temp_name)
        driver = make_driver(directory, args.headless, args.driver_path)
        try:
            with SessionLocal() as db:
                query = db.query(ProcedureGroup).filter(
                    ProcedureGroup.status == ProcedureGroupStatus.DRAFT)
                if args.code:
                    query = query.filter(ProcedureGroup.code == args.code)
                query = query.order_by(ProcedureGroup.created_at.asc())
                if args.limit is not None:
                    query = query.limit(args.limit)
                groups = query.all()
                LOGGER.info("Tìm thấy %d thủ tục DRAFT", len(groups))

                for position, group in enumerate(groups, 1):
                    LOGGER.info("[%d/%d] %s - %s", position, len(groups), group.code, group.name)
                    try:
                        scraped = scrape_procedure(driver, group.code, directory, args.timeout)
                        prefix = f"procedures/{safe_name(group.code)}"
                        document_url = upload_file(
                            s3, bucket, region, scraped.detail_pdf,
                            f"{prefix}/detail/{safe_name(scraped.detail_pdf.name, 'detail.pdf')}")
                        form_urls = list(dict.fromkeys(scraped.form_links))
                        for number, form_path in enumerate(scraped.form_files, 1):
                            form_urls.append(upload_file(
                                s3, bucket, region, form_path,
                                f"{prefix}/forms/{number:02d}-{safe_name(form_path.name)}"))

                        version = latest_version(group)
                        version.page_url = scraped.page_url
                        version.document_url = document_url
                        version.form_urls = list(dict.fromkeys(form_urls))
                        # Hai trường tóm tắt này cũng tồn tại ở bảng procedures.
                        group.page_url = scraped.page_url
                        group.document_url = document_url
                        db.commit()
                        succeeded += 1
                    except Exception:
                        db.rollback()
                        failed += 1
                        LOGGER.exception("Xử lý thất bại thủ tục %s", group.code)
                    finally:
                        for path in directory.iterdir():
                            if path.is_file():
                                try:
                                    path.unlink()
                                except OSError:
                                    LOGGER.warning("Không xoá được file tạm %s", path)
        finally:
            driver.quit()
    LOGGER.info("Hoàn tất: %d thành công, %d thất bại", succeeded, failed)
    return 1 if failed else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl tài liệu cho ProcedureGroup DRAFT")
    parser.add_argument("--code", help="Chỉ xử lý một mã thủ tục")
    parser.add_argument("--limit", type=int, help="Số thủ tục tối đa")
    parser.add_argument("--timeout", type=int, default=25, help="Timeout Selenium (giây)")
    parser.add_argument(
        "--driver-path",
        default=DEFAULT_DRIVER_PATH,
        help=f"ChromeDriver tương thích (mặc định: {DEFAULT_DRIVER_PATH})",
    )
    parser.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--verbose", action="store_true")
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
