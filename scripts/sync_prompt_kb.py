#!/usr/bin/env python3
"""Rebuild the vector index for context.txt (prompt KB)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from app.llm.prompt_kb import save_index, sync_prompt_kb_index  # noqa: E402


def main() -> int:
    index = sync_prompt_kb_index()
    path = save_index(index)
    print(json.dumps({"ok": True, "path": str(path), "chunk_count": index["chunk_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())