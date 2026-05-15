from langchain_core.tools import tool
import json
import re
import tempfile
import urllib.parse
from pathlib import Path
from typing import Annotated, TypedDict

import fitz  # PyMuPDF
import requests
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from app.helpers.utils.common import _llm

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
def select_form_url(qa_answer: str, user_input: str) -> str:
    """
    Phân tích câu trả lời từ QA node để chọn đúng PDF URL cần điền.

    Args:
        qa_answer:    Toàn bộ câu trả lời từ QA node (chứa các URL mẫu đơn).
        user_input: Yêu cầu của người dùng, ví dụ "điền mẫu CC01"
                      hoặc "điền mẫu đề nghị cấp lại căn cước".

    Returns:
        JSON với một trong hai trường hợp:
        - status="found"    → selected_url sẵn sàng truyền cho load_pdf_from_url
        - status="ambiguous" → candidates + câu hỏi để hỏi lại người dùng
        - status="not_found" → không tìm thấy URL nào
    """
    try:
        # 1. Trích xuất tất cả URL kết thúc bằng .pdf từ qa_answer
        raw_urls: list[str] = re.findall(
            r'https?://[^\s\)\]\>"\']+\.pdf',
            qa_answer,
            flags=re.IGNORECASE,
        )

        if not raw_urls:
            return json.dumps({
                "status": "not_found",
                "message": "Không tìm thấy URL PDF nào trong câu trả lời của QA node.",
            }, ensure_ascii=False)

        # Giải mã tên file để LLM dễ hiểu hơn
        url_info = []
        for url in raw_urls:
            parsed = urllib.parse.urlparse(url)
            raw_name = parsed.path.rstrip("/").split("/")[-1]
            filename = urllib.parse.unquote(raw_name).replace(".pdf", "")
            url_info.append({"url": url, "filename_decoded": filename})

        # 2. Nếu chỉ có 1 URL duy nhất → trả luôn không cần hỏi LLM
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
def load_pdf_from_url(pdf_url: str) -> str:
    """
    Tải file PDF từ URL về máy cục bộ.
    Hỗ trợ URL tên file tiếng Việt (raw Unicode hoặc percent-encoded).
    Trả về JSON: {success, pdf_path, filename, page_count, file_size_kb, message}
    """
    try:
        parsed = urllib.parse.urlparse(pdf_url)
        safe_path = urllib.parse.quote(parsed.path, safe="/")
        safe_url = parsed._replace(path=safe_path).geturl()

        resp = requests.get(safe_url, headers={"User-Agent": "FormsAgent/1.0"}, timeout=30)
        resp.raise_for_status()

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
 
Trả về JSON hợp lệ duy nhất, KHÔNG markdown, KHÔNG giải thích:
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
def extract_form_fields(pdf_path: str) -> str:
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
 
 
# ─────────────────────────────────────────────────────────────
# Tool điền PDF dùng field_positions từ extract_form_fields
# ─────────────────────────────────────────────────────────────
 
@tool
def fill_form_fields(pdf_path: str, field_values: dict, font_path: str = FONT_PATH) -> str:
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
        output_path = str(base.parent / f"{base.stem}_filled.pdf")
        doc.save(output_path, deflate=True)
        doc.close()

        return json.dumps({
            "success": True,
            "output_path": output_path,
            "filled": filled,
            "not_found": not_found,
            "message": f"Đã điền {len(filled)} trường. Lưu tại: {output_path}",
        }, ensure_ascii=False)

    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})
# ─────────────────────────────────────────────────────────────
# TOOL 4: Render preview PNG từng trang
# ─────────────────────────────────────────────────────────────

@tool
def preview_filled_form(pdf_path: str, dpi: int = 120) -> str:
    """
    Render các trang của PDF thành ảnh PNG để người dùng kiểm tra trước khi nộp.
    Trả về JSON: {success, preview_paths, total_pages, message}
    """
    try:
        doc = fitz.open(pdf_path)
        out_dir = Path(pdf_path).parent / "previews"
        out_dir.mkdir(exist_ok=True)
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        paths = []
        for i, page in enumerate(doc):
            p = out_dir / f"page_{i+1:02d}.png"
            page.get_pixmap(matrix=mat, alpha=False).save(str(p))
            paths.append(str(p))
        doc.close()
        return json.dumps({
            "success": True,
            "preview_paths": paths,
            "total_pages": len(paths),
            "message": f"Preview {len(paths)} trang tại: {out_dir}",
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)})