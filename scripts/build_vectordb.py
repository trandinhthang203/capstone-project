from typing import TypedDict, NotRequired

from langchain.agents import create_agent, AgentState
from langchain.agents.middleware import dynamic_prompt
from langchain.tools import tool, ToolRuntime
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
import os
load_dotenv()

KEY = os.getenv("GEMINI_API_KEY")


# =========================================================
# 1) RUNTIME CONTEXT + STATE SCHEMA
# ---------------------------------------------------------
# Context = dữ liệu "tĩnh" của một lần invoke
# State   = dữ liệu "ngắn hạn" của cuộc hội thoại hiện tại
# =========================================================

class RuntimeContext(TypedDict):
    user_role: str            # "beginner" | "expert"
    preferred_language: str   # "vi" | "en"


class MainState(AgentState):
    project_topic: NotRequired[str]
    target_audience: NotRequired[str]


# =========================================================
# 2) SIMPLE LOCAL TOOLS FOR SUBAGENTS
# ---------------------------------------------------------
# Dùng tool nội bộ để ví dụ có thể tự chạy / dễ hiểu.
# Trong production bạn có thể thay bằng search, DB, RAG, API...
# =========================================================

INTERNAL_KB = {
    "rag": """
RAG (Retrieval-Augmented Generation) là kỹ thuật kết hợp truy xuất tài liệu
với mô hình ngôn ngữ. Thay vì để LLM trả lời chỉ bằng kiến thức đã học sẵn,
hệ thống sẽ truy xuất các tài liệu liên quan rồi đưa chúng vào context trước
khi sinh câu trả lời.

Ưu điểm:
- Giảm bịa thông tin (hallucination)
- Cập nhật được tri thức mới
- Giúp trả lời dựa trên tài liệu nội bộ

Quy trình cơ bản:
1. Nhận câu hỏi
2. Biến câu hỏi thành truy vấn
3. Tìm tài liệu liên quan
4. Nhét tài liệu vào prompt/context
5. LLM tạo câu trả lời dựa trên tài liệu đó
""".strip(),
    "agents": """
Agent là hệ thống dùng LLM để quyết định khi nào cần gọi tool và lặp lại nhiều bước
để hoàn thành tác vụ. Multi-agent là hệ thống có nhiều agent chuyên biệt phối hợp với nhau.
""".strip(),
}


@tool
def lookup_internal_kb(query: str) -> str:
    """Tra cứu kho kiến thức nội bộ mẫu."""
    q = query.lower()
    if "rag" in q:
        return INTERNAL_KB["rag"]
    if "agent" in q:
        return INTERNAL_KB["agents"]
    return "Không tìm thấy mục phù hợp trong internal KB."


@tool
def count_words(text: str) -> str:
    """Đếm số từ trong bản nháp."""
    count = len(text.split())
    return f"Số từ ước tính: {count}"


# =========================================================
# 3) BUILD SUBAGENTS
# ---------------------------------------------------------
# Mỗi subagent có nhiệm vụ hẹp + output format rõ ràng.
# Đây là context engineering ở cấp "subagent specs" + "outputs".
# =========================================================

research_model = ChatGoogleGenerativeAI(api_key = KEY, model="gemini-2.5-flash", temperature=0.0)
writer_model = ChatGoogleGenerativeAI(api_key = KEY, model="gemini-2.5-flash", temperature=0.2)
supervisor_model = ChatGoogleGenerativeAI(api_key = KEY, model="gemini-2.5-flash", temperature=0.0)

research_subagent = create_agent(
    model=research_model,
    tools=[lookup_internal_kb],
    system_prompt=(
        "Bạn là RESEARCH SUBAGENT.\n"
        "Nhiệm vụ duy nhất của bạn là nghiên cứu và tổng hợp fact.\n"
        "KHÔNG viết bài hoàn chỉnh cho người dùng.\n"
        "Nếu cần tra cứu, dùng tool lookup_internal_kb.\n"
        "\n"
        "Bắt buộc trả về đúng format:\n"
        "SUMMARY:\n"
        "<tóm tắt 3-5 câu>\n\n"
        "KEY_FACTS:\n"
        "- <fact 1>\n"
        "- <fact 2>\n"
        "- <fact 3>\n\n"
        "RISKS_OR_LIMITS:\n"
        "- <điểm cần lưu ý>\n"
    ),
)

writer_subagent = create_agent(
    model=writer_model,
    tools=[count_words],
    system_prompt=(
        "Bạn là WRITER SUBAGENT.\n"
        "Nhiệm vụ duy nhất của bạn là viết lại nội dung rõ ràng, mạch lạc, dễ hiểu.\n"
        "Bạn phải dựa trên research notes được cung cấp, không tự bịa fact mới.\n"
        "Nếu độc giả là beginner, hãy giải thích đơn giản, có ví dụ ngắn.\n"
        "Nếu độc giả là expert, có thể súc tích và dùng thuật ngữ chính xác hơn.\n"
        "\n"
        "Bắt buộc trả về đúng format:\n"
        "TITLE: <tiêu đề>\n\n"
        "DRAFT:\n"
        "<nội dung hoàn chỉnh>\n"
    ),
)


# =========================================================
# 4) WRAP SUBAGENTS AS TOOLS
# ---------------------------------------------------------
# Đây là phần quan trọng nhất của subagents pattern:
# main agent gọi subagents như tool.
#
# Context engineering ở đây:
# - KHÔNG đưa toàn bộ context một cách bừa bãi
# - Chỉ đóng gói đúng phần state/context cần thiết
# - Mỗi subagent làm việc trong "clean context window"
# =========================================================

@tool("research_subagent", return_direct=False)
def call_research_subagent(query: str, runtime: ToolRuntime) -> str:
    """
    Giao việc nghiên cứu cho research subagent.
    """
    project_topic = runtime.state.get("project_topic", "")
    target_audience = runtime.state.get("target_audience", "general reader")
    user_role = runtime.context.get("user_role", "beginner")

    packed_input = f"""
NHIỆM VỤ:
{query}

PROJECT_TOPIC:
{project_topic}

TARGET_AUDIENCE:
{target_audience}

USER_ROLE:
{user_role}

YÊU CẦU:
- Chỉ nghiên cứu và tóm tắt fact
- Không viết bài hoàn chỉnh
- Nếu có khái niệm trọng tâm, giải thích thật rõ
""".strip()

    result = research_subagent.invoke({
        "messages": [{"role": "user", "content": packed_input}]
    })

    return result["messages"][-1].content


@tool("writer_subagent", return_direct=False)
def call_writer_subagent(query: str, runtime: ToolRuntime) -> str:
    """
    Giao việc viết nội dung cho writer subagent.
    """
    target_audience = runtime.state.get("target_audience", "general reader")
    preferred_language = runtime.context.get("preferred_language", "vi")
    user_role = runtime.context.get("user_role", "beginner")

    packed_input = f"""
NHIỆM VỤ:
{query}

TARGET_AUDIENCE:
{target_audience}

PREFERRED_LANGUAGE:
{preferred_language}

USER_ROLE:
{user_role}

YÊU CẦU:
- Viết bằng ngôn ngữ ở PREFERRED_LANGUAGE
- Dựa vào research notes đã có trong ngữ cảnh hội thoại
- Không bịa thêm facts ngoài research notes
- Nếu là beginner, giải thích bằng ngôn ngữ đời thường hơn
""".strip()

    result = writer_subagent.invoke({
        "messages": [{"role": "user", "content": packed_input}]
    })

    return result["messages"][-1].content


# =========================================================
# 5) DYNAMIC PROMPT FOR MAIN AGENT (MIDDLEWARE)
# ---------------------------------------------------------
# Đây là context engineering ở lớp "life-cycle / model context":
# prompt của main agent đổi theo user_role.
# =========================================================

@dynamic_prompt
def supervisor_prompt(request) -> str:
    user_role = request.runtime.context.get("user_role", "beginner")
    preferred_language = request.runtime.context.get("preferred_language", "vi")

    base = f"""
Bạn là MAIN SUPERVISOR AGENT.

Bạn có 2 tool:
1. research_subagent
   - Dùng khi cần tìm fact, khái niệm, tóm tắt tài liệu, phân tích nội dung
2. writer_subagent
   - Dùng khi cần chuyển research notes thành bài viết dễ hiểu, mạch lạc

NGUYÊN TẮC ĐIỀU PHỐI:
- Với câu hỏi tri thức không tầm thường, hãy gọi research_subagent trước.
- Chỉ gọi writer_subagent sau khi đã có đủ research notes.
- Không để writer_subagent tự phát minh fact.
- Câu trả lời cuối cùng cho người dùng phải bằng: {preferred_language}
- Main agent là người trả lời cuối cùng cho user.
""".strip()

    if user_role == "beginner":
        return (
            base
            + "\n\nPHONG CÁCH TRẢ LỜI:\n"
              "- Giải thích chậm, rõ, ít jargon\n"
              "- Nếu có thuật ngữ, phải định nghĩa ngắn gọn\n"
              "- Ưu tiên ví dụ thực tế"
        )

    return (
        base
        + "\n\nPHONG CÁCH TRẢ LỜI:\n"
          "- Có thể súc tích hơn\n"
          "- Dùng thuật ngữ kỹ thuật chính xác\n"
          "- Tập trung vào độ đúng và cấu trúc"
    )


# =========================================================
# 6) BUILD MAIN AGENT
# =========================================================

main_agent = create_agent(
    model=supervisor_model,
    tools=[call_research_subagent, call_writer_subagent],
    middleware=[supervisor_prompt],
    context_schema=RuntimeContext,
    state_schema=MainState,
)


# =========================================================
# 7) RUN EXAMPLE
# ---------------------------------------------------------
# context=...  -> static runtime context
# input state  -> messages + short-term task state
# =========================================================

if __name__ == "__main__":
    user_request = (
        "Hãy giải thích RAG là gì, tại sao nó hữu ích, "
        "và cho tôi một ví dụ rất đơn giản dành cho người mới học."
    )

    result = main_agent.invoke(
        {
            "messages": [
                {"role": "user", "content": user_request}
            ],
            "project_topic": "Retrieval-Augmented Generation (RAG)",
            "target_audience": "lập trình viên mới học LLM",
        },
        context={
            "user_role": "beginner",
            "preferred_language": "vi",
        },
    )

    print("\n===== FINAL ANSWER =====\n")
    print(result["messages"][-1].content)
