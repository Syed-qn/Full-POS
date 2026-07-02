#!/usr/bin/env python3
"""Specification traceability lint (E-24).

Greets prompt files for NEVER/ALWAYS constraint lines missing a ``# spec:`` comment
on the same line or the line immediately above.

Default targets (full prompt inventory — docs/prompt-inventory.md):
  - src/app/llm/conversation_prompts.py (E-12 SSOT)
  - src/app/llm/deepseek.py (provider assembly)
  - src/app/llm/complaint_agent.py, modify_agent.py, thought_evaluator.py
  - src/app/llm/prompts_router.py, prompts_menu.py, prompts_kitchen.py, prompts_marketing.py

Usage:
    python scripts/lint_prompt_spec_refs.py
    python scripts/lint_prompt_spec_refs.py src/app/llm/deepseek.py
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

_DEFAULT_PATHS = (
    _REPO_ROOT / "src/app/llm/conversation_prompts.py",
    _REPO_ROOT / "src/app/llm/deepseek.py",
    _REPO_ROOT / "src/app/llm/complaint_agent.py",
    _REPO_ROOT / "src/app/llm/modify_agent.py",
    _REPO_ROOT / "src/app/llm/thought_evaluator.py",
    _REPO_ROOT / "src/app/llm/prompts_router.py",
    _REPO_ROOT / "src/app/llm/prompts_menu.py",
    _REPO_ROOT / "src/app/llm/prompts_kitchen.py",
    _REPO_ROOT / "src/app/llm/prompts_marketing.py",
)

_RULE_RE = re.compile(r"\b(NEVER|ALWAYS)\b")
_SPEC_RE = re.compile(r"#\s*spec:")


def _lines_needing_spec(path: Path) -> list[tuple[int, str]]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    raw_lines = text.splitlines()
    violations: list[tuple[int, str]] = []
    for idx, line in enumerate(raw_lines):
        if not _RULE_RE.search(line):
            continue
        prev = raw_lines[idx - 1] if idx > 0 else ""
        if _SPEC_RE.search(line) or _SPEC_RE.search(prev):
            continue
        violations.append((idx + 1, line.strip()))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint NEVER/ALWAYS spec references (E-24)")
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="Prompt files to scan (default: full inventory in docs/prompt-inventory.md)",
    )
    args = parser.parse_args(argv)

    paths = args.files or list(_DEFAULT_PATHS)
    resolved = [
        p if p.is_absolute() else _REPO_ROOT / p
        for p in paths
    ]
    existing = [p for p in resolved if p.is_file()]
    if not existing:
        print("lint_prompt_spec_refs: no prompt files found to scan", file=sys.stderr)
        return 0

    total = 0
    for path in existing:
        hits = _lines_needing_spec(path)
        if not hits:
            continue
        rel = path.relative_to(_REPO_ROOT)
        print(f"{rel}: {len(hits)} NEVER/ALWAYS line(s) without # spec:")
        for lineno, content in hits:
            print(f"  {lineno}: {content[:120]}")
        total += len(hits)

    if total:
        print(
            f"\n{total} violation(s). Add `# spec: §section` on the rule line or line above.",
            file=sys.stderr,
        )
        return 1
    print("lint_prompt_spec_refs: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())