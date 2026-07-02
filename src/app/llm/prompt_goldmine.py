"""Load context.txt — authoritative prompt archive (DO NOT DELETE).

context.txt holds the full prompt goldmine from chat + git history. Runtime LLM
calls compose from conversation_prompts.py; this module loads the archive for
review tooling, regression scripts, and optional dev-time injection.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDMINE_PATH = _REPO_ROOT / "context.txt"


@lru_cache(maxsize=1)
def load_prompt_goldmine() -> str:
    """Return full context.txt text. Raises FileNotFoundError if missing."""
    if not GOLDMINE_PATH.is_file():
        raise FileNotFoundError(
            f"Prompt goldmine missing: {GOLDMINE_PATH}. "
            "Restore context.txt — it must not be deleted."
        )
    return GOLDMINE_PATH.read_text(encoding="utf-8")


def goldmine_line_count() -> int:
    return len(load_prompt_goldmine().splitlines())