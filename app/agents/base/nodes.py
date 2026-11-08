from __future__ import annotations

import os
import time
import hashlib
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt

from app.agents.base.memory import recall, remember
from app.agents.base.retrieval import retrieve_legal, retrieve_procedures
from app.agents.base.state import AgentState, QueryUnderstanding, StreamEvent
from app.agents.base.utils import emit
from app.helpers.utils.common import _create_llm, build_llm_messages, invoke_llm_text

def _text(message: Any) -> str:
    return str(getattr(message, "content", message))

def _timed(name: str, started: float, state: AgentState) -> dict[str, float]:
    timings = dict(state.get("node_timings_ms", {}))
    timings[name] = round((time.perf_counter() - started) * 1000, 2)
    return timings

async def history_summary(state: AgentState, config: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    messages = state.get("messages", [])
    # Retrieval evidence is request-scoped; checkpointed conversation memory is not.
    update: dict[str, Any] = {"procedure_results": [], "legal_results": []}
    threshold = int(os.getenv("CHAT_SUMMARY_THRESHOLD", "12"))
    summarized = state.get("summarized_message_count", 0)
    if len(messages) - summarized > threshold:
        recent = int(os.getenv("CHAT_RECENT_MESSAGES", "6"))
        source = "\n".join(_text(message) for message in messages[:-recent])
        update["history_summary"] = await invoke_llm_text([
            SystemMessage(content="Tóm tắt ngắn gọn, giữ ý định, thực thể, dữ kiện và các lần làm rõ."),
            HumanMessage(content=f"Tóm tắt cũ: {state.get('history_summary', '')}\n{source}")])
        update["summarized_message_count"] = max(0, len(messages) - recent)
        
    query = state.get("user_input") or (messages and _text(messages[-1])) or ""
    user_id = str(config.get("configurable", {}).get("user_id") or state.get("user_id", ""))
    update["long_term_memory"] = await recall(user_id, query)
    update["node_timings_ms"] = _timed("history_summary", started, state)
    return update

async def understand_query(state: AgentState) -> dict[str, Any]:
    started = time.perf_counter()
    query = state.get("user_input") or _text(state.get("messages", [""])[-1])
    prompt = """Phân tích câu hỏi cho chatbot thủ tục hành chính Việt Nam và Luật Hôn nhân & Gia đình.
Phân loại chitchat, out_of_scope, procedure, legal hoặc both; viết lại câu hỏi theo ngữ cảnh; trích xuất thực thể. Chỉ yêu cầu làm rõ khi thiếu dữ kiện thiết yếu."""
    llm = _create_llm().with_structured_output(QueryUnderstanding)
    context = state.get("history_summary", "")
    memory = state.get("long_term_memory", "")
    result = await llm.ainvoke([SystemMessage(content=f"{prompt}\nTóm tắt: {context}\nGhi nhớ: {memory}"),
                                HumanMessage(content=query)])
    return {
        **result.model_dump(),
        "clarification_question": result.clarification_question or "",
        "node_timings_ms": _timed("understand_query", started, state)
    }

async def direct_reply(state: AgentState) -> dict[str, Any]:
    started = time.perf_counter()
    if state.get("intent") == "out_of_scope":
        answer = "Tôi hỗ trợ thủ tục hành chính Việt Nam và Luật Hôn nhân và Gia đình. Bạn có thể hỏi tôi về một trong hai lĩnh vực này."
    else:
        answer = await invoke_llm_text(build_llm_messages(
            "Trả lời thân thiện, ngắn gọn bằng tiếng Việt. Không bịa thông tin pháp lý.",
            state.get("messages", []), state.get("history_summary", "")))
    await remember(state.get("user_id", ""), state.get("original_query", ""), answer)
    return {
        "final_answer": answer,
        "messages": [AIMessage(content=answer)],
        "node_timings_ms": _timed("direct_reply", started, state)
    }

async def ask_clarify(state: AgentState) -> dict[str, Any]:
    started = time.perf_counter()
    question = state.get("clarification_question") or "Bạn vui lòng cung cấp thêm thông tin."
    request_id = hashlib.sha256(f"{state.get('thread_id', '')}:{state.get('original_query', '')}".encode()).hexdigest()[:20]
    answer = interrupt({"kind": "dynamic_form", "request_id": request_id,
                        "title": "Cần thêm thông tin", "description": question,
                        "submit_label": "Tiếp tục", "fields": [{"field_id": "clarification",
                        "label": question, "type": "textarea", "required": True}]})
    text = " ".join(str(v) for v in answer.values()) if isinstance(answer, dict) else str(answer)
    combined = f"{state.get('original_query', '')}\nThông tin làm rõ: {text}".strip()
    return {
        "user_input": combined, 
        "messages": [HumanMessage(content=text)],
        "needs_clarification": False, 
        "clarification_count": state.get("clarification_count", 0) + 1,
        "node_timings_ms": _timed("ask_clarify", started, state)
    }

async def procedure_retrieval(state: AgentState) -> dict[str, Any]:
    started = time.perf_counter()
    await emit(StreamEvent("progress", "procedure_retrieval", "Đang tra cứu thủ tục hành chính"))
    results = await retrieve_procedures(state["rewritten_query"], state.get("user_role", "USER"))
    return {"procedure_results": results, "node_timings_ms": _timed("procedure_retrieval", started, state)}

async def legal_retrieval(state: AgentState) -> dict[str, Any]:
    started = time.perf_counter()
    await emit(StreamEvent("progress", "legal_retrieval", "Đang tra cứu văn bản pháp luật"))
    results = await retrieve_legal(state["rewritten_query"], state.get("entities", {}))
    return {"legal_results": results, "node_timings_ms": _timed("legal_retrieval", started, state)}

async def context_builder(state: AgentState) -> dict[str, Any]:
    started = time.perf_counter()
    evidence = [*state.get("procedure_results", []), *state.get("legal_results", [])]
    if not evidence:
        answer = "Tôi chưa tìm thấy nguồn phù hợp để trả lời chắc chắn. Bạn vui lòng nêu rõ tên/mã thủ tục hoặc vấn đề pháp lý."
        return {"context_sufficient": False, "missing_information": "Không tìm thấy bằng chứng",
                "final_answer": answer, "final_response": answer, "citations": [],
                "messages": [AIMessage(content=answer)], "node_timings_ms": _timed("context_builder", started, state)}
    context = "\n\n".join(f"[{i}] {item.get('title', '')}\n{item.get('passage', '')}"
                            for i, item in enumerate(evidence, 1))
    answer = await invoke_llm_text([SystemMessage(content="Trả lời bằng tiếng Việt chỉ dựa trên bằng chứng; trích dẫn [1], [2]; nói rõ khi nguồn thiếu.\n" + context),
                                    HumanMessage(content=state["rewritten_query"])])
    await remember(state.get("user_id", ""), state.get("original_query", ""), answer)
    citations = [{"index": i, "title": item.get("title"), "url": item.get("url"),
                  "document_id": item.get("document_id"), "procedure_code": item.get("procedure_code"),
                  "source_type": item.get("source_type")} for i, item in enumerate(evidence, 1)]
    await emit(StreamEvent("result", "context_builder", answer, {"citations": citations}))
    return {
        "context_sufficient": True, 
        "final_answer": answer, 
        "messages": [AIMessage(content=answer)],
        "node_timings_ms": _timed("context_builder", started, state)
    }
