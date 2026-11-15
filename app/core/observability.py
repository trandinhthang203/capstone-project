import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator


logger = logging.getLogger(__name__)


def langfuse_is_configured() -> bool:
    """Return whether the credentials required by Langfuse are present."""
    return bool(
        os.getenv("LANGFUSE_PUBLIC_KEY")
        and os.getenv("LANGFUSE_SECRET_KEY")
    )


@contextmanager
def trace_graph_call(
    *,
    user_id: str | None,
    session_id: str,
) -> Iterator[list[Any]]:
    """Attach Langfuse tracing to one graph call when it is configured.

    The callback records the LangGraph/LangChain hierarchy, including model
    usage and timing. Attribute propagation makes the resulting metrics
    filterable and aggregatable by user and chat session.
    """
    if not langfuse_is_configured():
        yield []
        return

    try:
        from langfuse import propagate_attributes
        from langfuse.langchain import CallbackHandler
    except ImportError:
        logger.warning(
            "Langfuse credentials are configured but the 'langfuse' package "
            "is not installed; graph tracing is disabled."
        )
        yield []
        return

    with propagate_attributes(
        trace_name="dvc-agent-graph",
        user_id=str(user_id) if user_id is not None else None,
        session_id=session_id,
        tags=["langgraph", "chat"],
        metadata={"component": "message_service"},
    ):
        yield [CallbackHandler()]
