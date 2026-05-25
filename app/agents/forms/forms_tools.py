from langchain_core.tools import tool
import json
import tempfile
import urllib.parse
from pathlib import Path

import fitz  # PyMuPDF
import requests
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from app.helpers.utils.common import _llm
from scripts.process_forms import ProcessForms

_process_forms = ProcessForms()
# ─────────────────────────────────────────────────────────────
# TOOL
# ─────────────────────────────────────────────────────────────

FONT_PATH = "E:/ttf/DejaVuSans.ttf"

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
"""


@tool
async def select_form_url(pdf_urls: list[dict], user_input: str) -> str:
    """
    Chọn đúng PDF URL từ danh sách biểu mẫu đã được QA node trích xuất.

    Args:
        pdf_urls:   Danh sách dict với keys 'loai_giay_to' và 'mau_don_to_khai',
                    ví dụ: [{"loai_giay_to": "Mẫu DC02...", "mau_don_to_khai": "https://...pdf"}]
        user_input: Yêu cầu của người dùng, ví dụ "điền mẫu CC01".

    Returns:
        JSON với status "found" | "ambiguous" | "not_found"
    """
    try:
        # 1. Lọc những mẫu có URL hợp lệ
        url_info = [
            {
                "url": item["mau_don_to_khai"],
                "filename_decoded": item["loai_giay_to"],
            }
            for item in pdf_urls
            if item.get("mau_don_to_khai", "").strip()
        ]

        if not url_info:
            return json.dumps({
                "status": "not_found",
                "message": "Không có biểu mẫu nào có URL PDF hợp lệ.",
            }, ensure_ascii=False)

        # 2. Chỉ 1 URL → trả luôn
        if len(url_info) == 1:
            return json.dumps({
                "status": "found",
                "selected_url": url_info[0]["url"],
                "form_name": url_info[0]["filename_decoded"],
            }, ensure_ascii=False)

        # 3. Nhiều URL → nhờ LLM khớp với yêu cầu người dùng
        user_content = (
            f"Yêu cầu người dùng: {user_input}\n\n"
            f"Danh sách URL mẫu đơn:\n"
            + json.dumps(url_info, ensure_ascii=False, indent=2)
        )

        response = _llm.invoke([
            SystemMessage(content=SYSTEM_PROMPT_SELECT),
            HumanMessage(content=user_content),
        ])

        raw = response.content.strip().removeprefix("```json").removesuffix("```").strip()
        result = json.loads(raw)
        return json.dumps(result, ensure_ascii=False)

    except Exception as exc:
        import traceback
        return json.dumps({
            "status": "error",
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }, ensure_ascii=False)

@tool
async def load_pdf_from_url(pdf_url: str) -> str:
    """
    Tải file PDF từ URL về máy cục bộ.
    Hỗ trợ URL tên file tiếng Việt (raw Unicode hoặc percent-encoded).
    Trả về JSON: {success, pdf_path, filename, page_count, file_size_kb, message}
    """
    try:
        # Decode trước để về Unicode thuần, rồi encode đúng 1 lần
        # parsed = urllib.parse.urlparse(pdf_url)
        # decoded_path = urllib.parse.unquote(parsed.path)        # decode về raw
        # safe_path = urllib.parse.quote(decoded_path, safe="/")  # encode đúng 1 lần
        # safe_url = parsed._replace(path=safe_path).geturl()

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

        print(f"pdf_path: {str(pdf_path)}")

        return json.dumps({
            "success": True,
            "pdf_path": str(pdf_path),
            "filename": filename,
            "page_count": page_count,
            "file_size_kb": round(len(resp.content) / 1024, 1),
            "message": f"Đã tải '{filename}' ({page_count} trang).",
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})


# ─────────────────────────────────────────────────────────────
# SYSTEM PROMPT
# ─────────────────────────────────────────────────────────────
 
SYSTEM_PROMPT_EXTRAC = """Bạn là chuyên gia phân tích mẫu đơn hành chính Việt Nam.
 
Bạn nhận được danh sách các text span trích xuất từ PDF, mỗi span gồm:
  - text: nội dung văn bản
  - bbox: (x0, y0, x1, y1) – tọa độ trong PDF (gốc trên-trái)
 
Nhiệm vụ:
1. Xác định các trường cần điền (label kèm dấu ":" hoặc dấu "…", "_", "/")
2. Với mỗi trường, trả về tọa độ điền = (x1 của label + 2, y0 của label)
   tức là ngay sau phần label, để text điền không đè lên label.
 
Trả về JSON hợp lệ duy nhất, KHÔNG markdown, KHÔNG giải thích, ví dụ:
{
  "fields": [
    {
      "field_id": "ho_ten",
      "label": "Họ, chữ đệm và tên khai sinh",
      "x": 212.0,
      "y": 100.2
    }
  ]
}"""
 
 
# ─────────────────────────────────────────────────────────────
# TOOL
# ─────────────────────────────────────────────────────────────
 
@tool
async def extract_form_fields(pdf_path: str) -> str:
    """
    Trích xuất các trường cần điền và tọa độ từ PDF tĩnh tiếng Việt.
 
    Quy trình:
      1. Dùng PyMuPDF lấy text + bbox từng span
      2. Gửi toàn bộ lên LLM
      3. LLM trả về field_id, label, (x, y) để điền
 
    Trả về JSON:
      {success, pdf_path, total_fields,
       fields: [{field_id, label, x, y}]}
    """
    try:
        try:
            pdf_path = pdf_path.encode('latin-1').decode('unicode_escape').encode('latin-1').decode('utf-8')
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
                        all_spans.append({
                            "page": pno,
                            "text": text,
                            "bbox": [round(x0,1), round(y0,1), round(x1,1), round(y1,1)],
                        })
 
        doc.close()
 
        user_content = (
            "Đây là các span text từ PDF:\n\n"
            + json.dumps(all_spans, ensure_ascii=False, indent=2)
        )
 
        response = _llm.invoke([
            SystemMessage(content=SYSTEM_PROMPT_EXTRAC),
            HumanMessage(content=user_content),
        ])
 
        raw = response.content.strip().removeprefix("```json").removesuffix("```").strip()
        parsed = json.loads(raw)
        fields = parsed.get("fields", [])
 
        print(f"[extract_form_fields_v2] Tìm được {len(fields)} trường")
 
        return json.dumps({
            "success": True,
            "pdf_path": pdf_path,
            "total_fields": len(fields),
            "fields": fields,
        }, ensure_ascii=False)
 
    except Exception as exc:
        import traceback
        return json.dumps({"success": False, "error": str(exc), "traceback": traceback.format_exc()})

@tool
async def fill_form_fields(pdf_path: str, field_values: dict, font_path: str = FONT_PATH) -> str:
    """
    Điền giá trị vào PDF.

    Args:
        pdf_path:     Đường dẫn PDF gốc.
        field_values: {field_id: {"value": "...", "x": float, "y": float}}
                      – tọa độ lấy từ kết quả extract_form_fields.
        font_path:    Đường dẫn .ttf hỗ trợ tiếng Việt.
    """
    try:
        doc = fitz.open(pdf_path)
        page = doc[0]
        filled, not_found = [], []

        for field_id, info in field_values.items():
            value = info.get("value", "")
            x = info.get("x")
            y = info.get("y")

            if not value or x is None or y is None:
                not_found.append(field_id)
                continue

            insert_kwargs = dict(
                point=fitz.Point(x, y + 10),
                text=str(value),
                fontsize=9,
                color=(0, 0, 0),
            )
            if font_path:
                insert_kwargs["fontfile"] = font_path
                insert_kwargs["fontname"] = "DejaVu"

            page.insert_text(**insert_kwargs)
            filled.append(field_id)

        base = Path(pdf_path)
        output_path = f"/tmp/{base.stem}_filled.pdf"
        doc.save(output_path, deflate=True)
        doc.close()

        pdf_url = _process_forms.gen_url_file(output_path)

        Path(output_path).unlink(missing_ok=True)

        return json.dumps({
            "success": True,
            "pdf_url": pdf_url,
            "filled": filled,
            "not_found": not_found,
            "message": f"Đã điền {len(filled)} trường.",
        }, ensure_ascii=False)

    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})
# ─────────────────────────────────────────────────────────────
# TOOL 4: Render preview PNG từng trang
# ─────────────────────────────────────────────────────────────

# @tool
# async def preview_filled_form(pdf_path: str, dpi: int = 120) -> str:
#     """
#     Render các trang của PDF thành ảnh PNG để người dùng kiểm tra trước khi nộp.
#     Trả về JSON: {success, preview_paths, total_pages, message}
#     """
#     try:
#         doc = fitz.open(pdf_path)
#         out_dir = Path(pdf_path).parent / "previews"
#         out_dir.mkdir(exist_ok=True)
#         mat = fitz.Matrix(dpi / 72, dpi / 72)
#         paths = []
#         for i, page in enumerate(doc):
#             p = out_dir / f"page_{i+1:02d}.png"
#             page.get_pixmap(matrix=mat, alpha=False).save(str(p))
#             paths.append(str(p))
#         doc.close()
#         return json.dumps({
#             "success": True,
#             "preview_paths": paths,
#             "total_pages": len(paths),
#             "message": f"Preview {len(paths)} trang tại: {out_dir}",
#         }, ensure_ascii=False)
#     except Exception as exc:
#         return json.dumps({"success": False, "error": str(exc)})