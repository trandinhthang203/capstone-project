from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from typing import Any

import yaml


PROMPT_DIR = Path(__file__).resolve().parent
_PROMPT_NAME_PATTERN = re.compile(r"^[a-z0-9_]+$")


@lru_cache(maxsize=None)
def load_system_prompt(name: str) -> str:
    """Load and validate a versioned system prompt from ``app/prompts``."""
    if not _PROMPT_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"Invalid prompt name: {name!r}")

    path = PROMPT_DIR / f"{name}.yaml"
    try:
        with path.open(encoding="utf-8") as prompt_file:
            data: Any = yaml.safe_load(prompt_file)
    except FileNotFoundError as exc:
        raise ValueError(f"Prompt not found: {name}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Prompt {name!r} must be a YAML mapping")

    prompt = data.get("system")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"Prompt {name!r} must define a non-empty 'system' value")

    return prompt.strip()
