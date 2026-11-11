from __future__ import annotations

import os
import time
import hashlib
import asyncio
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt

# Memory tạm thời bị vô hiệu hóa. Bỏ comment khi cần bật lại Mem0.
# from app.agents.base.memory import recall, remember
from app.agents.base.retrieval import retrieve_legal, retrieve_procedures
from app.agents.base.state import AgentState, QueryUnderstanding, StreamEvent
from app.agents.base.utils import emit, _text, _normalize_procedure_text, _timed
from app.agents.SQLAgent import aquery_database
from app.helpers.utils.common import _create_llm, build_llm_messages, invoke_llm_text
from scripts.ingestion.indexing import PAYLOAD_INDEX_FIELDS, search_procedures

async def history_summary(state: AgentState) -> dict[str, Any]:
    started = time.perf_counter()
    messages = state.get("messages", [])
    # Retrieval evidence is request-scoped; checkpointed conversation memory is not.
    update: dict[str, Any] = {
        "procedure_results": [], "legal_results": [],
        "procedure_candidates": [],
    }
    threshold = int(os.getenv("CHAT_SUMMARY_THRESHOLD", "12"))
    summarized = state.get("summarized_message_count", 0)
    if len(messages) - summarized > threshold:
        recent = int(os.getenv("CHAT_RECENT_MESSAGES", "6"))
        source = "\n".join(_text(message) for message in messages[:-recent])
        update["history_summary"] = await invoke_llm_text([
            SystemMessage(content="Tóm tắt ngắn gọn, giữ ý định, thực thể, dữ kiện và các lần làm rõ."),
            HumanMessage(content=f"Tóm tắt cũ: {state.get('history_summary', '')}\n{source}")])
        update["summarized_message_count"] = max(0, len(messages) - recent)
        
    # TODO(memory): Bật lại các dòng dưới khi tiếp tục sử dụng Mem0.
    # query = state.get("user_input") or (messages and _text(messages[-1])) or ""
    # user_id = str(config.get("configurable", {}).get("user_id") or state.get("user_id", ""))
    # update["long_term_memory"] = await recall(user_id, query)
    update["long_term_memory"] = ""
    update["node_timings_ms"] = _timed("history_summary", started, state)
    return update

async def understand_query(state: AgentState) -> dict[str, Any]:
    started = time.perf_counter()
    query = state.get("user_input") or _text(state.get("messages", [""])[-1])
    prompt = """Bạn là bộ định tuyến truy vấn cho chatbot về thủ tục hành chính Việt Nam và Luật Hôn nhân & Gia đình.

Nhiệm vụ:
1. Phân loại chính xác một trong: chitchat, out_of_scope, procedure, legal, both.
2. Viết lại câu hỏi độc lập, giữ nguyên ý định và dữ kiện từ hội thoại.
   - Luôn đọc các tin nhắn gần nhất để hiểu câu hỏi nối tiếp, rút gọn hoặc
     thiếu chủ ngữ, ví dụ: "hồ sơ thì sao", "còn lệ phí?", "thời hạn bao lâu".
   - Nếu câu hiện tại hỏi tiếp về đối tượng, thủ tục hoặc vấn đề pháp luật ở
     lượt trước, phải kế thừa ngữ cảnh và intent tương ứng. Không phân loại là
     chitchat hoặc out_of_scope chỉ vì câu hiện tại ngắn.
   - rewritten_query phải bổ sung đối tượng từ ngữ cảnh. Ví dụ, sau câu hỏi về
     trình tự đăng ký kết hôn, "hồ sơ thì sao" phải được viết lại thành "Hồ sơ
     thực hiện thủ tục đăng ký kết hôn gồm những gì?".
3. Nếu intent là procedure và thuộc dạng câu hỏi cần xác định trước thủ tục, bắt buộc trích procedure_name: chỉ là tên/cụm từ nhận diện thủ tục để hybrid search, bỏ các phần hỏi như hồ sơ, lệ phí, thời hạn, cách làm. Không tự bịa tên.
    Ví dụ: "Đăng ký kết hôn cần giấy tờ gì?" => intent=procedure, procedure_name="Đăng ký kết hôn".
4. Nếu intent là procedure nhưng thuộc dạng câu hỏi không cần xác định thủ tục, hoặc dạng câu hỏi truy vấn tổng hợp, thống kê,...thì để procedure_name là null.
    Ví dụ: "Lĩnh vực đất đai của xã tôi có bao nhiêu thủ tục?" => intent=procedure, procedure_name=null.
"""
    llm = _create_llm().with_structured_output(QueryUnderstanding)
    context = state.get("history_summary", "")
    # Memory tạm thời để trống; đổi lại thành state.get(...) khi bật Mem0.
    memory = ""
    messages = state.get("messages", [])
    llm_messages = build_llm_messages(
        prompt,
        messages,
        summary=context,
        extra_system_context=f"Ghi nhớ dài hạn:\n{memory}" if memory else "",
    )
    # Bình thường message hiện tại đã nằm cuối checkpoint. Vẫn bổ sung nó cho
    # caller/test chỉ truyền user_input, nhưng không nhân đôi ở luồng chính.
    if not messages or _text(messages[-1]).strip() != query.strip():
        llm_messages.append(HumanMessage(content=query))
    result = await llm.ainvoke(llm_messages)
    update = {
        **result.model_dump(),
        "node_timings_ms": _timed("understand_query", started, state)
    }
    if result.intent == "procedure":
        procedure_name = (result.procedure_name or "").strip()
        active_code = state.get("selected_procedure_code", "").strip()
        active_name = state.get("selected_procedure_name", "").strip()
        normalized_active = _normalize_procedure_text(active_name)
        normalized_name = _normalize_procedure_text(procedure_name)
        normalized_query = _normalize_procedure_text(
            str(update.get("rewritten_query") or query)
        )

        # Reuse the authoritative code selected in a previous turn when the
        # model resolves this follow-up to the same procedure. This avoids a
        # duplicate embedding + Qdrant search and another confirmation form.
        if procedure_name:
            same_active_procedure = bool(
                active_code
                and normalized_active
                and (
                    normalized_name == normalized_active
                    or normalized_name in normalized_active
                    or normalized_active in normalized_name
                )
            )
        else:
            same_active_procedure = bool(
                active_code
                and normalized_active
                and normalized_active in normalized_query
            )

        if same_active_procedure:
            update.update({
                "selected_procedure_code": active_code,
                "selected_procedure_name": active_name,
                "procedure_candidates": [],
                "needs_clarification": False,
                "clarification_question": "",
            })
        elif procedure_name:
            # The user switched to another named procedure. Clear the previous
            # selection before searching and asking for a new confirmation.
            update["selected_procedure_code"] = ""
            update["selected_procedure_name"] = ""

            allowed = set(PAYLOAD_INDEX_FIELDS)
            filters: dict[str, str | list[str]] = {
                k: v.strip()
                for k, v in state.get("procedure_filters", {}).items()
                if k in allowed and isinstance(v, str) and v.strip()
            }
            if state.get("user_role", "USER").upper() in {"EDITOR", "ADMIN"}:
                filters["status"] = ["archived", "published"]
            else:
                filters["status"] = "published"
            top_k = max(1, int(os.getenv("PROCEDURE_NAME_TOP_K", "5")))
            candidates = await asyncio.to_thread(
                search_procedures, procedure_name, top_k, filters or None
            )
            update["procedure_candidates"] = candidates
            if candidates:
                update["needs_clarification"] = True
                update["clarification_question"] = (
                    "Vui lòng xác nhận thủ tục hành chính bạn muốn hỏi."
                )
            else:
                update["needs_clarification"] = True
                update["clarification_question"] = (
                    f"Tôi chưa tìm thấy thủ tục phù hợp với “{procedure_name}”. "
                    "Bạn vui lòng cho biết tên hoặc mã thủ tục cụ thể hơn."
                )
        elif active_code:
            # A procedure query unrelated to the active procedure must never
            # accidentally execute SQL with the stale code.
            update["selected_procedure_code"] = ""
            update["selected_procedure_name"] = ""
    return update

async def direct_reply(state: AgentState) -> dict[str, Any]:
    started = time.perf_counter()
    if state.get("intent") == "out_of_scope":
        answer = "Tôi hỗ trợ thủ tục hành chính Việt Nam và Luật Hôn nhân và Gia đình. Bạn có thể hỏi tôi về một trong hai lĩnh vực này."
    else:
        answer = await invoke_llm_text(build_llm_messages(
            "Trả lời thân thiện, ngắn gọn bằng tiếng Việt. Không bịa thông tin pháp lý.",
            state.get("messages", []), state.get("history_summary", "")))
    # TODO(memory): Bật lại khi cần lưu câu trả lời vào Mem0.
    # await remember(state.get("user_id", ""), state.get("original_query", ""), answer)
    return {
        "final_answer": answer,
        "messages": [AIMessage(content=answer)],
        "node_timings_ms": _timed("direct_reply", started, state)
    }

async def ask_clarify(state: AgentState) -> dict[str, Any]:
    started = time.perf_counter()
    question = state.get("clarification_question") or "Bạn vui lòng cung cấp thêm thông tin."
    request_id = hashlib.sha256(
        f"{state.get('session_id', '')}:{state.get('rewritten_query', state.get('user_input', ''))}".encode()
    ).hexdigest()[:20]
    candidates = state.get("procedure_candidates", [])
    if state.get("intent") == "procedure" and candidates:
        field = {
            "field_id": "procedure_code", "label": "Thủ tục hành chính",
            "type": "select", "required": True,
            "options": [
                {"value": str(item["code"]),
                 "label": f'{item.get("name", "")} ({item["code"]})'}
                for item in candidates if item.get("code")
            ],
        }
        title = "Xác nhận thủ tục"
    else:
        field = {"field_id": "clarification", "label": question,
                 "type": "textarea", "required": True}
        title = "Cần thêm thông tin"

    answer = interrupt(
        {
            "kind": "dynamic_form", 
            "request_id": request_id,
            "title": title, 
            "description": question,
            "submit_label": "Tiếp tục", 
            "fields": [field]
        }
    )
    text = " ".join(str(v) for v in answer.values()) if isinstance(answer, dict) else str(answer)
    combined = f"{state.get('user_input', '')}\nThông tin làm rõ: {text}".strip()
    update = {
        "user_input": combined, 
        "messages": [HumanMessage(content=text)],
        "needs_clarification": False, 
        "clarification_count": state.get("clarification_count", 0) + 1,
        "node_timings_ms": _timed("ask_clarify", started, state)
    }
    if state.get("intent") == "procedure" and candidates:
        selected_code = str(answer.get("procedure_code", "")) if isinstance(answer, dict) else text
        selected = next((item for item in candidates
                         if str(item.get("code")) == selected_code), None)
        if selected:
            update["selected_procedure_code"] = selected_code
            update["selected_procedure_name"] = str(selected.get("name") or "")
    return update

async def procedure(state: AgentState) -> dict[str, Any]:
    """Answer a procedure question using the HITL-confirmed procedure code."""
    started = time.perf_counter()
    await emit(StreamEvent("progress", "procedure", "Đang truy vấn dữ liệu thủ tục hành chính"))
    code = state.get("selected_procedure_code", "").strip()
    if not code:
        answer = (
            "Tôi chưa xác định được chính xác thủ tục hành chính bạn muốn hỏi. "
            "Bạn vui lòng gửi lại tên hoặc mã thủ tục cụ thể."
        )
        return {"final_answer": answer, "messages": [AIMessage(content=answer)],
                "node_timings_ms": _timed("procedure", started, state)}
    answer = await aquery_database(
        state.get("rewritten_query") or state.get("user_input", ""),
        state.get("user_role", "USER"),
        procedure_code=code,
    )
    await emit(StreamEvent("result", "procedure", answer,
                           {"procedure_code": code,
                            "procedure_name": state.get("selected_procedure_name", "")}))
    return {"final_answer": answer, "messages": [AIMessage(content=answer)],
            "node_timings_ms": _timed("procedure", started, state)}

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
    # TODO(memory): Bật lại khi cần lưu câu trả lời vào Mem0.
    # await remember(state.get("user_id", ""), state.get("original_query", ""), answer)
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
