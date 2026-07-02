#!/usr/bin/env python3
"""PromptPilot-style dev review loop (E-19) — static DO1–DO4 checklist.

Reads a prompt source file (and optional failing test name) and prints a markdown
review checklist. No LLM API calls.

Usage:
    python scripts/review_prompt_regression.py src/app/llm/deepseek.py
    python scripts/review_prompt_regression.py src/app/llm/deepseek.py \\
        --test tests/conversation/test_engine_ordering.py::test_cart_add
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GOLDMINE = _REPO_ROOT / "context.txt"

# Symbols that indicate prompt template / system blocks (SSOT + legacy + auxiliary).
_PROMPT_BLOCK_RE = re.compile(
    r"^("
    # Legacy deepseek private phase blocks (pre-E-02)
    r"_IDENTITY|_ORDERING_BLOCK|_ADDRESS_BLOCK|_CONFIRMATION_BLOCK|_POST_ORDER_BLOCK|"
    r"_CONVERSATION_SYSTEM|_POST_ORDER_GUIDANCE|"
    # E-02 SSOT — conversation_prompts.py
    r"IDENTITY_TEMPLATE|ORDERING_BLOCK_TEMPLATE|ADDRESS_BLOCK_TEMPLATE|"
    r"CONFIRMATION_BLOCK_TEMPLATE|POST_ORDER_BLOCK_TEMPLATE|"
    r"INTENT_BLOCK|META_LANGUAGE_BLOCK|OKF_GROUNDING_RULE|CLAUDE_POST_ORDER_GUIDANCE|"
    # Sub-agents (E-10, E-17)
    r"_COMPLAINT_SYSTEM|COMPLAINT_SYSTEM|_MODIFY_SYSTEM|MODIFY_SYSTEM|_TOT_SYSTEM|"
    # Auxiliary prompt modules
    r"EXTRACT_SYSTEM|DESCRIBE_DISH_TEMPLATE|ARBITRATE_TEMPLATE|INTENT_CLASSIFY_TEMPLATE|"
    r"SEGMENT_COMPILE_TEMPLATE|FORECAST_OVERRIDE_TEMPLATE|"
    r"ROUTER_CLASSIFY_TEMPLATE|COMPLETION_DETECT_TEMPLATE|"
    r"TIER2_SYSTEM|COPYWRITER_PROMPT"
    r")\s*=",
    re.MULTILINE,
)

_AUDIENCE_MARKERS = (
    "whatsapp",
    "customer",
    "restaurant",
    "host",
    "multilingual",
)
_PURPOSE_MARKERS = (
    "phase:",
    "ordering",
    "address",
    "post_order",
    "confirmation",
    "take_action",
    "action=",
)
_STRUCTURE_MARKERS = (
    "[role]",
    "[context]",
    "[task]",
    "[instructions]",
    "[constraints]",
    "decision order",
    "step 1",
    "rules:",
    "menu:",
    "current cart",
)
_SPECIFICITY_MARKERS = (
    "never",
    "always",
    "authoritative",
    "r-0",
    "spec §",
    "# spec:",
    "overrides",
    "exactly",
)
_LANGUAGE_MARKERS = (
    "tone",
    "friendly",
    "warm",
    "any language",
    "multilingual",
    "reply",
)


def _load_prompt_text(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


def _extract_blocks(text: str) -> list[tuple[str, str]]:
    """Return (symbol, block_body) for known prompt constants."""
    blocks: list[tuple[str, str]] = []
    for match in _PROMPT_BLOCK_RE.finditer(text):
        symbol = match.group(1)
        start = match.end()
        while start < len(text) and text[start] in " \t":
            start += 1
        # Triple-quoted string
        if text[start : start + 3] == '"""':
            end = text.find('"""', start + 3)
            if end == -1:
                continue
            body = text[start + 3 : end]
        elif text[start : start + 1] in {'"', "'"}:
            quote = text[start]
            end = text.find(quote, start + 1)
            if end == -1:
                continue
            body = text[start + 1 : end]
        else:
            continue
        blocks.append((symbol, body))
    if not blocks:
        blocks.append(("(full file)", text))
    return blocks


def _count_hits(blob: str, markers: tuple[str, ...]) -> list[str]:
    low = blob.lower()
    return [m for m in markers if m in low]


def _do1_flags(blob: str) -> dict[str, list[str]]:
    return {
        "audience": _count_hits(blob, _AUDIENCE_MARKERS),
        "purpose": _count_hits(blob, _PURPOSE_MARKERS),
        "structure": _count_hits(blob, _STRUCTURE_MARKERS),
        "specificity": _count_hits(blob, _SPECIFICITY_MARKERS),
        "language": _count_hits(blob, _LANGUAGE_MARKERS),
    }


def _never_always_without_spec(blob: str) -> list[str]:
    violations: list[str] = []
    for i, line in enumerate(blob.splitlines(), 1):
        if not re.search(r"\b(NEVER|ALWAYS)\b", line):
            continue
        prev = blob.splitlines()[i - 2] if i > 1 else ""
        if "# spec:" not in line and "# spec:" not in prev:
            violations.append(f"line {i}: {line.strip()[:100]}")
    return violations


def _render_checklist(
    path: Path,
    blocks: list[tuple[str, str]],
    *,
    test_name: str | None,
) -> str:
    lines: list[str] = [
        f"# Prompt regression review — `{path.relative_to(_REPO_ROOT)}`",
        "",
    ]
    if test_name:
        lines.extend([
            f"**Triggered by failing test:** `{test_name}`",
            "",
        ])

    # DO1 — error domain diagnosis
    lines.extend([
        "## DO1 — Error domain diagnosis",
        "",
        "Flag improvement potential before suggesting edits:",
        "",
    ])
    for symbol, body in blocks:
        flags = _do1_flags(body)
        lines.append(f"### `{symbol}`")
        lines.append("")
        for domain, hits in flags.items():
            status = "✓" if hits else "⚠ gap"
            sample = ", ".join(hits[:4]) if hits else "_none detected_"
            lines.append(f"- **{domain}** {status}: {sample}")
        spec_gaps = _never_always_without_spec(body)
        if spec_gaps:
            lines.append(f"- **spec traceability** ⚠: {len(spec_gaps)} NEVER/ALWAYS without `# spec:`")
        lines.append("")

    # DO2 — guided questions
    lines.extend([
        "## DO2 — Guided questions (answer before editing)",
        "",
        "1. What **dialogue phase(s)** does this block govern?",
        "2. Which **actions** are allowed vs forbidden in that phase?",
        "3. What is the **authoritative cart source** (context vs history)?",
        "4. Which rules should live in **engine.py** instead of the prompt?",
        "5. Is there a **failing pytest** or transcript that proves the gap?",
        "6. Does the change affect **DeepSeek and Claude** parity?",
        "",
    ])

    # DO3 — completion signal
    lines.extend([
        "## DO3 — Completion signal",
        "",
        "Merge only when all of the following are true:",
        "",
        "- [ ] DO1 gaps addressed or explicitly accepted",
        "- [ ] New/changed rules have `# spec: §…` references (run `lint_prompt_spec_refs.py`)",
        "- [ ] Prompt parity tests pass:",
        "  ```bash",
        "  pytest tests/llm/test_deepseek_prompt.py tests/llm/test_location_grounding.py \\",
        "         tests/llm/test_address_guardrails.py tests/llm/test_cart_state_prompt_precedence.py",
        "  ```",
        "- [ ] Conversation regressions pass:",
        "  ```bash",
        "  pytest tests/conversation/test_ok_post_order.py tests/conversation/test_engine_ordering.py",
        "  ```",
    ])
    if test_name:
        lines.append(f"- [ ] Failing test green: `pytest {test_name}`")
    lines.extend(["", "**Change summary:** _(fill in before merge)_", "",])

    # DO4 — user autonomy
    lines.extend([
        "## DO4 — User autonomy",
        "",
        "This script **never auto-edits** production prompts. Use the checklist above,",
        "apply edits manually, and re-run tests. Human merges the PR.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PromptPilot-style prompt review (E-19)")
    parser.add_argument(
        "prompt_file",
        type=Path,
        help="Path to prompt source (e.g. src/app/llm/deepseek.py)",
    )
    parser.add_argument(
        "--test",
        dest="test_name",
        default=None,
        help="Optional failing pytest node id for DO3 traceability",
    )
    args = parser.parse_args(argv)

    if not _GOLDMINE.is_file():
        print(
            "error: context.txt missing at repo root — restore before editing prompts",
            file=sys.stderr,
        )
        return 1

    path = args.prompt_file if args.prompt_file.is_absolute() else _REPO_ROOT / args.prompt_file
    try:
        text = _load_prompt_text(path)
    except FileNotFoundError:
        print(f"error: file not found: {path}", file=sys.stderr)
        return 1

    blocks = _extract_blocks(text)
    print(_render_checklist(path, blocks, test_name=args.test_name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())