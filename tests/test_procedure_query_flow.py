from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.base import nodes
from app.agents.base.graph import route_after_clarify, route_query
from app.agents.base.state import ProcedureFilters
from scripts.ingestion.indexing import PAYLOAD_INDEX_FIELDS


def test_procedure_filter_fields_match_payload_indexes():
    assert set(ProcedureFilters.__annotations__) == set(PAYLOAD_INDEX_FIELDS)


class _StructuredLLM:
    async def ainvoke(self, _messages):
        return SimpleNamespace(
            intent="procedure",
            rewritten_query="Hồ sơ đăng ký kết hôn gồm những gì?",
            entities={},
            needs_clarification=False,
            clarification_question=None,
            procedure_name="Đăng ký kết hôn",
            model_dump=lambda: {
                "intent": "procedure",
                "rewritten_query": "Hồ sơ đăng ký kết hôn gồm những gì?",
                "entities": {},
                "needs_clarification": False,
                "clarification_question": None,
                "procedure_name": "Đăng ký kết hôn",
            },
        )


class _LLM:
    def with_structured_output(self, _schema):
        return _StructuredLLM()


@pytest.mark.asyncio
async def test_understand_query_searches_name_with_safe_role_filter(monkeypatch):
    captured = {}

    def fake_search(query, top_k, filters):
        captured.update(query=query, top_k=top_k, filters=filters)
        return [{"code": "1.001", "name": "Đăng ký kết hôn", "score": 1.0}]

    monkeypatch.setattr(nodes, "_create_llm", lambda: _LLM())
    monkeypatch.setattr(nodes, "search_procedures", fake_search)

    result = await nodes.understand_query({
        "user_input": "Kết hôn cần giấy tờ gì?",
        "user_role": "USER",
        "procedure_filters": {
            "domain": "  Hộ tịch  ",
            "status": "archived",
        },
    })

    assert captured == {"query": "Đăng ký kết hôn", "top_k": 5,
                        "filters": {"domain": "Hộ tịch", "status": "published"}}
    assert result["procedure_candidates"][0]["code"] == "1.001"
    assert result["needs_clarification"] is True


@pytest.mark.asyncio
async def test_understand_query_searches_both_statuses_for_editor(monkeypatch):
    captured = {}

    def fake_search(query, top_k, filters):
        captured.update(query=query, top_k=top_k, filters=filters)
        return []

    monkeypatch.setattr(nodes, "_create_llm", lambda: _LLM())
    monkeypatch.setattr(nodes, "search_procedures", fake_search)

    await nodes.understand_query({
        "user_input": "Kết hôn cần giấy tờ gì?",
        "user_role": "EDITOR",
        "procedure_filters": {"domain": "Hộ tịch"},
    })

    assert captured["filters"] == {
        "domain": "Hộ tịch",
        "status": ["archived", "published"],
    }


@pytest.mark.asyncio
async def test_understand_query_uses_recent_messages_for_follow_up(monkeypatch):
    captured = {}

    class ContextAwareStructuredLLM:
        async def ainvoke(self, messages):
            captured["messages"] = messages
            contents = "\n".join(str(message.content) for message in messages)
            has_context = "trình tự" in contents and "đăng ký kết hôn" in contents
            intent = "procedure" if has_context else "out_of_scope"
            return SimpleNamespace(
                intent=intent,
                procedure_name=None,
                model_dump=lambda: {
                    "intent": intent,
                    "rewritten_query": (
                        "Hồ sơ thực hiện thủ tục đăng ký kết hôn gồm những gì?"
                    ),
                    "procedure_name": None,
                },
            )

    class ContextAwareLLM:
        def with_structured_output(self, _schema):
            return ContextAwareStructuredLLM()

    def fail_search(*_args, **_kwargs):
        raise AssertionError("follow-up cùng thủ tục không được retrieval lại")

    monkeypatch.setattr(nodes, "_create_llm", lambda: ContextAwareLLM())
    monkeypatch.setattr(nodes, "search_procedures", fail_search)
    result = await nodes.understand_query({
        "user_input": "Hồ sơ thì sao?",
        "selected_procedure_code": "1.001",
        "selected_procedure_name": "Đăng ký kết hôn",
        "messages": [
            HumanMessage(
                content="Trình tự thực hiện thủ tục đăng ký kết hôn là gì?"
            ),
            AIMessage(content="Thủ tục được thực hiện theo các bước..."),
            HumanMessage(content="Hồ sơ thì sao?"),
        ],
    })

    assert result["intent"] == "procedure"
    assert result["selected_procedure_code"] == "1.001"
    assert result["needs_clarification"] is False
    assert len(captured["messages"]) == 4  # system + 3 conversation messages
    assert captured["messages"][-1].content == "Hồ sơ thì sao?"


@pytest.mark.asyncio
async def test_understand_query_searches_again_when_procedure_changes(monkeypatch):
    captured = {}

    class ChangedProcedureStructuredLLM:
        async def ainvoke(self, _messages):
            return SimpleNamespace(
                intent="procedure",
                procedure_name="Đăng ký khai sinh",
                model_dump=lambda: {
                    "intent": "procedure",
                    "rewritten_query": "Hồ sơ đăng ký khai sinh gồm những gì?",
                    "procedure_name": "Đăng ký khai sinh",
                },
            )

    class ChangedProcedureLLM:
        def with_structured_output(self, _schema):
            return ChangedProcedureStructuredLLM()

    def fake_search(query, top_k, filters):
        captured.update(query=query, top_k=top_k, filters=filters)
        return [{"code": "2.002", "name": query, "score": 1.0}]

    monkeypatch.setattr(nodes, "_create_llm", lambda: ChangedProcedureLLM())
    monkeypatch.setattr(nodes, "search_procedures", fake_search)
    result = await nodes.understand_query({
        "user_input": "Còn hồ sơ đăng ký khai sinh?",
        "selected_procedure_code": "1.001",
        "selected_procedure_name": "Đăng ký kết hôn",
        "user_role": "USER",
    })

    assert captured["query"] == "Đăng ký khai sinh"
    assert result["selected_procedure_code"] == ""
    assert result["needs_clarification"] is True


def test_confirmed_procedure_routes_to_sql_node():
    assert route_query({"intent": "procedure", "needs_clarification": False,
                        "selected_procedure_code": "1.001"}) == "procedure"
    assert route_after_clarify({"intent": "procedure",
                                "selected_procedure_code": "1.001"}) == "procedure"


@pytest.mark.asyncio
async def test_procedure_uses_confirmed_code(monkeypatch):
    captured = {}

    async def fake_query(question, role, procedure_code=None):
        captured.update(question=question, role=role, procedure_code=procedure_code)
        return "Kết quả SQL"

    monkeypatch.setattr(nodes, "aquery_database", fake_query)
    monkeypatch.setattr(nodes, "emit", lambda _event: _noop())

    result = await nodes.procedure({"rewritten_query": "Cần giấy tờ gì?",
                                    "user_role": "USER",
                                    "selected_procedure_code": "1.001"})

    assert captured["procedure_code"] == "1.001"
    assert result["final_answer"] == "Kết quả SQL"


async def _noop():
    return None
