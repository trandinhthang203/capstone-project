import pytest

from app.prompts.loader import load_system_prompt


def test_load_understand_query_prompt():
    prompt = load_system_prompt("understand_query")

    assert "chitchat, out_of_scope, procedure, legal, both" in prompt
    assert "procedure_name" in prompt


def test_load_sql_agent_prompt_preserves_langchain_variables():
    prompt = load_system_prompt("sql_agent")

    assert "{dialect}" in prompt
    assert "{top_k}" in prompt
    assert "Never execute data-modifying SQL" in prompt


@pytest.mark.parametrize("name", ["../secret", "Understand-Query", "a/b"])
def test_prompt_loader_rejects_unsafe_names(name):
    with pytest.raises(ValueError, match="Invalid prompt name"):
        load_system_prompt(name)


def test_prompt_loader_reports_missing_prompt():
    with pytest.raises(ValueError, match="Prompt not found"):
        load_system_prompt("missing_prompt")
