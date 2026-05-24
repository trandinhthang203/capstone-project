import json
from app.agents.supervisor.constants import VALID_DOMAINS
from app.helpers.utils.logger import logging

def _parse_intent_response(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logging.warning(f"[intent_node] JSON parse failed: {raw!r}")
        return {
            "intent": "unclear",
            "domain": None,
            "confidence": 0.0,
            "chitchat_reply": None,
        }

def _validate_domain(domain: str | None) -> str | None:
    if domain and domain.lower() in VALID_DOMAINS:
        return domain.lower()
    return None