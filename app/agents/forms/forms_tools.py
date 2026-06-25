import io
import json
import os
import tempfile
import traceback
import urllib.parse
from pathlib import Path

import fitz  # PyMuPDF
import requests
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from app.helpers.utils.common import _llm
from scripts.process_forms import ProcessForms

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_ID = os.getenv("FOLDER_ID")
GOOGLE_REFRESH_TOKEN = os.getenv("GOOGLE_REFRESH_TOKEN")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

_process_forms = ProcessForms()

SYSTEM_PROMPT_SELECT = """Bạn là trợ lý phân tích danh sách mẫu đơn hành chính Việt Nam.

Bạn nhận được:
1. Danh sách các URL mẫu đơn (kèm tên file được suy ra từ URL)
2. Yêu cầu của người dùng (muốn điền mẫu nào)

Nhiệm vụ:
- Nếu yêu cầu khớp RÕ RÀNG với đúng 1 URL → trả về URL đó.
- Nếu không khớp rõ hoặc có nhiều URL có thể phù hợp → trả về danh sách để hỏi người dùng.

Trả về JSON hợp lệ duy nhất, KHÔNG markdown, KHÔNG giải thích:

Trường hợp 1 – tìm thấy đúng 1 mẫu:
{
  "status": "found",
  "selected_url": "https://...",
  "form_name": "Mẫu CC01 – Phiếu thu nhận thông tin căn cước"
}

Trường hợp 2 – cần hỏi thêm:
{
  "status": "ambiguous",
  "candidates": [
    {"url": "https://...", "form_name": "Mẫu CC01 – ..."},
    {"url": "https://...", "form_name": "Mẫu CC02 – ..."}
  ],
  "question": "Bạn muốn điền mẫu đơn nào trong số sau?"
}

Trường hợp 3 – không tìm thấy:
{
  "status": "not_found",
  "message": "Không tìm thấy mẫu đơn phù hợp"
}
"""

SYSTEM_PROMPT_EXTRAC = """Bạn là chuyên gia phân tích mẫu đơn hành chính Việt Nam.

Bạn nhận được danh sách các text span trích xuất từ PDF, mỗi span gồm:
  - page: số trang, bắt đầu từ 0
  - text: nội dung văn bản
  - bbox: (x0, y0, x1, y1) – tọa độ trong PDF (gốc trên-trái)

Nhiệm vụ:
1. Xác định các trường cần điền (label kèm dấu ":" hoặc vùng gạch dưới / dấu chấm / ô trống).
2. Với mỗi trường, BẮT BUỘC trả về:
   - field_id
   - label
   - page
   - x
   - y
3. page phải đúng theo span chứa label.
4. x là vị trí bắt đầu điền, thường là x1 của label + 2.
5. y là dòng cơ sở để điền text ngang hàng với label.

Trả về JSON hợp lệ duy nhất, KHÔNG markdown, KHÔNG giải thích, ví dụ:
{
  "fields": [
    {
      "field_id": "ho_ten",
      "label": "Họ, chữ đệm và tên khai sinh",
      "page": 0,
      "x": 212.0,
      "y": 100.2
    }
  ]
}"""


class DriveUploadError(Exception):
    """Lỗi tổng quát khi xử lý convert PDF sang Google Doc."""



def _missing_google_drive_config() -> list[str]:
    missing = []
    if not FOLDER_ID:
        missing.append("FOLDER_ID")
    if not GOOGLE_REFRESH_TOKEN:
        missing.append("GOOGLE_REFRESH_TOKEN")
    if not GOOGLE_CLIENT_ID:
        missing.append("GOOGLE_CLIENT_ID")
    if not GOOGLE_CLIENT_SECRET:
        missing.append("GOOGLE_CLIENT_SECRET")
    return missing



def _get_drive_service():
    missing = _missing_google_drive_config()
    if missing:
        raise DriveUploadError(
            "Thiếu cấu hình Google Drive: " + ", ".join(missing)
        )

    creds = Credentials(
        token=None,
        refresh_token=GOOGLE_REFRESH_TOKEN,
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("drive", "v3", credentials=creds)



def _resolve_font_path(font_path: str | None = None) -> str | None:
    candidates = [
        font_path,
        os.getenv("PDF_FONT_PATH"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]

    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


@tool
async def select_form_url(pdf_urls: list[dict], user_input: str) -> str:
    """
    Chọn đúng PDF URL từ danh sách biểu mẫu đã được QA node trích xuất.

    Args:
        pdf_urls: Danh sách dict với keys 'loai_giay_to' và 'mau_don_to_khai'.
        user_input: Yêu cầu của người dùng.

    Returns:
        JSON với status "found" | "ambiguous" | "not_found"
    """
    try:
        url_info = [
            {
                "url": item["mau_don_to_khai"],
                "filename_decoded": item["loai_giay_to"],
            }
            for item in pdf_urls
            if item.get("mau_don_to_khai", "").strip()
        ]

        if not url_info:
            return json.dumps(
                {
                    "status": "not_found",
                    "message": "Không có biểu mẫu nào có URL PDF hợp lệ.",
                },
                ensure_ascii=False,
            )

        if len(url_info) == 1:
            return json.dumps(
                {
                    "status": "found",
                    "selected_url": url_info[0]["url"],
                    "form_name": url_info[0]["filename_decoded"],
                },
                ensure_ascii=False,
            )

        user_content = (
            f"Yêu cầu người dùng: {user_input}\n\n"
            f"Danh sách URL mẫu đơn:\n"
            + json.dumps(url_info, ensure_ascii=False, indent=2)
        )

        response = _llm.invoke(
            [
                SystemMessage(content=SYSTEM_PROMPT_SELECT),
                HumanMessage(content=user_content),
            ]
        )

        raw = (
            str(response.content)
            .strip()
            .removeprefix("```json")
            .removesuffix("```")
            .strip()
        )
        result = json.loads(raw)
        return json.dumps(result, ensure_ascii=False)

    except Exception as exc:
        return json.dumps(
            {
                "status": "error",
                "error": str(exc),
                "traceback": traceback.format_exc(),
            },
            ensure_ascii=False,
        )


@tool
async def get_google_docs_link(s3_url: str, file_name: str, user_email: str | None = None) -> str:
    """
    Tải PDF từ URL, upload lên Google Drive và convert thành Google Doc, sau đó cấp quyền chỉnh sửa.
    """
    try:
        drive_service = _get_drive_service()

        try:
            response = requests.get(s3_url, stream=True, timeout=30)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise DriveUploadError(f"Không thể tải file nguồn: {exc}") from exc

        file_stream = io.BytesIO(response.content)
        file_metadata = {
            "name": file_name,
            "mimeType": "application/vnd.google-apps.document",
            "parents": [FOLDER_ID],
        }
        media = MediaIoBaseUpload(file_stream, mimetype="application/pdf", resumable=True)

        try:
            uploaded_file = (
                drive_service.files()
                .create(body=file_metadata, media_body=media, fields="id")
                .execute()
            )
        except Exception as exc:
            raise DriveUploadError(f"Lỗi upload Drive: {exc}") from exc

        file_id = uploaded_file["id"]

        try:
            if user_email:
                drive_service.permissions().create(
                    fileId=file_id,
                    body={"role": "writer", "type": "user", "emailAddress": user_email},
                ).execute()
            else:
                drive_service.permissions().create(
                    fileId=file_id,
                    body={"role": "writer", "type": "anyone"},
                ).execute()
        except Exception as exc:
            raise DriveUploadError(f"Lỗi cấp quyền: {exc}") from exc

        embed_url = f"https://docs.google.com/document/d/{file_id}/edit?usp=sharing"
        return json.dumps(
            {
                "success": True,
                "file_id": file_id,
                "embed_url": embed_url,
            },
            ensure_ascii=False,
        )

    except DriveUploadError as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps(
            {
                "success": False,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            },
            ensure_ascii=False,
        )


@tool
async def load_pdf_from_url(pdf_url: str) -> str:
    """
    Tải file PDF từ URL về máy cục bộ.
    Hỗ trợ URL tên file tiếng Việt.
    Trả về JSON: {success, pdf_path, filename, page_count, file_size_kb, message}
    """
    try:
        resp = requests.get(pdf_url, headers={"User-Agent": "FormsAgent/1.0"}, timeout=30)
        resp.raise_for_status()

        parsed = urllib.parse.urlparse(pdf_url)
        raw_name = parsed.path.rstrip("/").split("/")[-1]
        filename = urllib.parse.unquote(raw_name)
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"

        tmp_dir = Path(tempfile.mkdtemp(prefix="forms_"))
        pdf_path = tmp_dir / filename
        pdf_path.write_bytes(resp.content)

        with fitz.open(str(pdf_path)) as doc:
            page_count = len(doc)

        return json.dumps(
            {
                "success": True,
                "pdf_path": str(pdf_path),
                "filename": filename,
                "page_count": page_count,
                "file_size_kb": round(len(resp.content) / 1024, 1),
                "message": f"Đã tải '{filename}' ({page_count} trang).",
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)


@tool
async def extract_form_fields(pdf_path: str) -> str:
    """
    Trích xuất các trường cần điền và tọa độ từ PDF tĩnh tiếng Việt.
    """
    try:
        try:
            pdf_path = (
                pdf_path.encode("latin-1")
                .decode("unicode_escape")
                .encode("latin-1")
                .decode("utf-8")
            )
        except (UnicodeDecodeError, UnicodeEncodeError):
            pass

        doc = fitz.open(pdf_path)
        all_spans = []

        for pno, page in enumerate(doc):
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span["text"].strip()
                        if not text:
                            continue
                        x0, y0, x1, y1 = span["bbox"]
                        all_spans.append(
                            {
                                "page": pno,
                                "text": text,
                                "bbox": [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)],
                            }
                        )

        doc.close()

        user_content = (
            "Đây là các span text từ PDF:\n\n"
            + json.dumps(all_spans, ensure_ascii=False, indent=2)
        )

        response = _llm.invoke(
            [
                SystemMessage(content=SYSTEM_PROMPT_EXTRAC),
                HumanMessage(content=user_content),
            ]
        )

        raw = (
            str(response.content)
            .strip()
            .removeprefix("```json")
            .removesuffix("```")
            .strip()
        )
        parsed = json.loads(raw)
        fields = parsed.get("fields", [])

        return json.dumps(
            {
                "success": True,
                "pdf_path": pdf_path,
                "total_fields": len(fields),
                "fields": fields,
            },
            ensure_ascii=False,
        )

    except Exception as exc:
        return json.dumps(
            {
                "success": False,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            },
            ensure_ascii=False,
        )


@tool
async def fill_form_fields(pdf_path: str, field_values: dict, font_path: str | None = None) -> str:
    """
    Điền giá trị vào PDF nhiều trang.

    field_values:
    {
      "field_id": {
        "value": "...",
        "x": 123.4,
        "y": 456.7,
        "page": 0
      }
    }
    """
    try:
        doc = fitz.open(pdf_path)
        total_pages = len(doc)
        resolved_font = _resolve_font_path(font_path)

        filled, not_found = [], []

        for field_id, info in field_values.items():
            value = str(info.get("value", "")).strip()
            x = info.get("x")
            y = info.get("y")
            page_no = int(info.get("page", 0) or 0)

            if not value or x is None or y is None:
                not_found.append(field_id)
                continue

            if page_no < 0 or page_no >= total_pages:
                not_found.append(field_id)
                continue

            page = doc[page_no]
            rect = fitz.Rect(
                float(x),
                max(0, float(y) - 2),
                page.rect.width - 24,
                float(y) + 14,
            )

            textbox_kwargs = {
                "rect": rect,
                "buffer": value,
                "fontsize": 9,
                "color": (0, 0, 0),
                "align": 0,
            }

            if resolved_font:
                textbox_kwargs["fontfile"] = resolved_font
                textbox_kwargs["fontname"] = "FormFont"

            rc = page.insert_textbox(**textbox_kwargs)

            if rc < 0:
                text_kwargs = {
                    "point": fitz.Point(float(x), float(y) + 8),
                    "text": value,
                    "fontsize": 9,
                    "color": (0, 0, 0),
                }
                if resolved_font:
                    text_kwargs["fontfile"] = resolved_font
                    text_kwargs["fontname"] = "FormFont"
                page.insert_text(**text_kwargs)

            filled.append(field_id)

        base = Path(pdf_path)
        output_path = f"/tmp/{base.stem}_filled.pdf"
        doc.save(output_path, deflate=True)
        doc.close()

        pdf_url = _process_forms.gen_url_file(output_path)
        Path(output_path).unlink(missing_ok=True)

        return json.dumps(
            {
                "success": True,
                "pdf_url": pdf_url,
                "filled": filled,
                "not_found": not_found,
                "message": f"Đã điền {len(filled)} trường.",
                "font_used": resolved_font,
            },
            ensure_ascii=False,
        )

    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)
