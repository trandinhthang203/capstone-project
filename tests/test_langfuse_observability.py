import sys
from contextlib import contextmanager
from types import ModuleType
from uuid import uuid4

from app.core.observability import trace_graph_call
from app.services.message_service import MessageService


def test_graph_config_contains_langfuse_grouping_metadata():
    session_id = uuid4()
    service = MessageService(db=None, user_id="user-123")

    config = service._build_config(session_id)

    assert config["configurable"]["thread_id"] == str(session_id)
    assert config["metadata"]["langfuse_user_id"] == "user-123"
    assert config["metadata"]["langfuse_session_id"] == str(session_id)
    assert config["run_name"] == "handle-chat-message"


def test_trace_graph_call_propagates_user_and_session(monkeypatch):
    captured = {}
    fake_langfuse = ModuleType("langfuse")
    fake_langchain = ModuleType("langfuse.langchain")

    @contextmanager
    def propagate_attributes(**attributes):
        captured.update(attributes)
        yield

    class CallbackHandler:
        pass

    fake_langfuse.propagate_attributes = propagate_attributes
    fake_langchain.CallbackHandler = CallbackHandler
    monkeypatch.setitem(sys.modules, "langfuse", fake_langfuse)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", fake_langchain)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")

    with trace_graph_call(user_id="user-123", session_id="session-456") as callbacks:
        assert len(callbacks) == 1
        assert isinstance(callbacks[0], CallbackHandler)

    assert captured["trace_name"] == "dvc-agent-graph"
    assert captured["user_id"] == "user-123"
    assert captured["session_id"] == "session-456"
