"""LangChain agent for querying the application's PostgreSQL database."""

from __future__ import annotations

import asyncio
import json
import os
from functools import lru_cache
from typing import Any

from dotenv import load_dotenv
from langchain_community.agent_toolkits import create_sql_agent
from langchain_community.utilities import SQLDatabase
from langchain_classic.agents.agent import AgentExecutor

from app.helpers.utils.common import _create_llm

load_dotenv()

TABLES = [
    "procedures",
    "procedure",
    "method",
    "component",
    "component_document",
    "basis",
]

SQL_AGENT_PREFIX = """
You are a PostgreSQL Text-to-SQL agent specializing
in Vietnamese administrative procedures.

DATABASE DOMAIN:
The database stores structured information about
Vietnamese administrative procedures.

TABLE SELECTION RULES:
1. procedures:
   Identify procedures by code or name.

2. procedure:
   Retrieve detailed administrative procedure information,
   including steps, requirements, agencies and results.

3. method:
   Retrieve submission methods and execution channels.

4. component:
   Retrieve required application components.

5. component_document:
   Retrieve specific required documents and copies.

6. basis:
   Retrieve legal references and legal foundations.

IMPORTANT DISTINCTIONS:
- procedures is the parent entity.
- procedure stores detailed records.
- steps means the execution sequence.
- method means the submission/execution channel.
- requirements means eligibility conditions.
- component and component_document describe application documents.
- basis describes legal grounds.

QUERY GENERATION RULES:
- Always inspect relevant table schemas before querying.
- Only use columns that actually exist.
- Use foreign keys to determine valid JOIN paths.
- Never assume a column exists.
- Do not invent relationships between tables.
- Use the correct detail record when multiple versions exist.
- Never execute data-modifying SQL.
- Check SQL before execution.
- If the query fails, correct it and retry.
- Do not invent missing information.
- When PROCEDURE_CODE is provided in the user input, identify the procedure only
  with an exact predicate on procedures.code (for example,
  procedures.code = '...'). Do not use LIKE or ILIKE on procedures.code,
  procedures.name, or procedure.name as a fallback.
- Join procedure details through procedure.procedure_id = procedures.id.

DATABASE DIALECT:
{dialect}

DEFAULT RESULT LIMIT:
{top_k}

Return the final answer in Vietnamese.
"""


@lru_cache(maxsize=2)
def get_sql_database(access_level: str):
    if access_level == "citizen":
        url = os.environ["CITIZEN_SQL_DATABASE_URL"]
    elif access_level == "staff":
        url = os.environ["STAFF_SQL_DATABASE_URL"]
    else:
        raise ValueError("Invalid access level")

    return SQLDatabase.from_uri(
        url,
        include_tables=TABLES,
        sample_rows_in_table_info=0,
        engine_args={
            "pool_pre_ping": True,
            "connect_args": {
                "options": (
                    "-c search_path=public "
                    "-c default_transaction_read_only=on "
                    "-c statement_timeout=5000"
                )
            },
        },
    )


@lru_cache(maxsize=2)
def get_sql_agent(access_level: str):
    return create_sql_agent(
        llm=_create_llm(),
        db=get_sql_database(access_level),
        agent_type="tool-calling",
        prefix=SQL_AGENT_PREFIX,
        verbose=True,
    )


def _build_agent_input(question: str, procedure_code: str | None = None) -> str:
    """Build the agent input, including an authoritative procedure code."""
    question = question.strip()
    if not question:
        raise ValueError("question must not be empty")

    if procedure_code is None:
        return question

    procedure_code = procedure_code.strip()
    if not procedure_code:
        raise ValueError("procedure_code must not be empty")

    # JSON encoding keeps the supplied value unambiguous in the prompt. The SQL
    # agent must still inspect the schema and generate the exact equality filter.
    encoded_code = json.dumps(procedure_code, ensure_ascii=False)
    return f"""{question}

AUTHORITATIVE PROCEDURE CONTEXT:
PROCEDURE_CODE: {encoded_code}
The procedure has already been identified by the application. You MUST filter
with an exact equality predicate on procedures.code using PROCEDURE_CODE.
Do not search for or re-identify the procedure by name. Do not use LIKE or
ILIKE on procedures.code, procedures.name, or procedure.name.
"""


def query_database(
    question: str,
    role: str,
    procedure_code: str | None = None,
):
    if role == "USER":
        access_level = "citizen"
    elif role in ("EDITOR", "ADMIN"):
        access_level = "staff"
    else:
        raise PermissionError("Invalid role")

    agent = get_sql_agent(access_level)

    result = agent.invoke({
        "input": _build_agent_input(question, procedure_code)
    })

    return result["output"]


async def aquery_database(
    question: str,
    role: str,
    procedure_code: str | None = None,
) -> str:
    """Asynchronous version of :func:`query_database`."""
    if role == "USER":
        access_level = "citizen"
    elif role in ("EDITOR", "ADMIN"):
        access_level = "staff"
    else:
        raise PermissionError("Invalid role")

    agent = get_sql_agent(access_level)
    payload = {"input": _build_agent_input(question, procedure_code)}
    if hasattr(agent, "ainvoke"):
        result: dict[str, Any] = await agent.ainvoke(payload)
    else:
        result = await asyncio.to_thread(agent.invoke, payload)
    return str(result.get("output", ""))


__all__ = [
    "aquery_database",
    "get_sql_agent",
    "get_sql_database",
    "query_database",
]

