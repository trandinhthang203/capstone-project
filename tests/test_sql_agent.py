from app.agents import SQLAgent


class _FakeAgent:
    def __init__(self):
        self.payload = None

    def invoke(self, payload):
        self.payload = payload
        return {"output": "ok"}


def test_query_database_supplies_exact_procedure_code_context(monkeypatch):
    agent = _FakeAgent()
    monkeypatch.setattr(SQLAgent, "get_sql_agent", lambda access_level: agent)

    result = SQLAgent.query_database(
        "Cần chuẩn bị giấy tờ gì?",
        "USER",
        procedure_code="1.001456",
    )

    assert result == "ok"
    assert 'PROCEDURE_CODE: "1.001456"' in agent.payload["input"]
    assert "exact equality predicate on procedures.code" in agent.payload["input"]
    assert "Do not use LIKE or" in agent.payload["input"]


def test_query_database_keeps_general_question_unchanged(monkeypatch):
    agent = _FakeAgent()
    monkeypatch.setattr(SQLAgent, "get_sql_agent", lambda access_level: agent)

    SQLAgent.query_database("  Có bao nhiêu thủ tục?  ", "ADMIN")

    assert agent.payload == {"input": "Có bao nhiêu thủ tục?"}

