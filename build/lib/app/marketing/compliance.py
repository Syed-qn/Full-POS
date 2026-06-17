"""WhatsApp marketing template compliance linter.

Pure function ``lint_template(spec) -> list[str]`` returning a list of
violation strings (empty list = compliant). Mirrors the AI-generator
pre-submission checklist so templates pass Meta review on the first pass.

Source of rules: docs/research/meta-template-compliance.md §3 (technical
rules) + §6 (best-practice checklist).
"""
from __future__ import annotations

import re

_MAX_NAME_LEN = 512
_MAX_BODY_LEN = 1024
_MAX_FOOTER_LEN = 60
_MAX_HEADER_LEN = 60
_MAX_BUTTON_LABEL_LEN = 25
_MAX_BUTTONS = 10
_MAX_URL_BUTTONS = 2
_MAX_BODY_LINES = 5

_NAME_RE = re.compile(r"^[a-z0-9_]+$")
_VAR_RE = re.compile(r"\{\{\s*(\d+)\s*\}\}")
_ADJACENT_VARS_RE = re.compile(r"\}\}\s*\{\{")
_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_ANY_URL_RE = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_TRIPLE_NEWLINE_RE = re.compile(r"\n{3,}")

_SHORTENER_HOSTS = ("bit.ly", "tinyurl", "t.co", "goo.gl")

# Emoji unicode ranges (broad coverage of pictographs, symbols, flags).
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # symbols, pictographs, supplemental, emoticons
    "\U00002600-\U000027BF"  # misc symbols + dingbats
    "\U0001F1E6-\U0001F1FF"  # regional indicators (flags)
    "\U00002190-\U000021FF"  # arrows
    "\U00002B00-\U00002BFF"  # misc symbols & arrows
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U00002700-\U000027BF"
    "]",
    flags=re.UNICODE,
)


def _has_emoji(text: str) -> bool:
    return bool(_EMOJI_RE.search(text))


def _has_shortener(text: str) -> str | None:
    lowered = text.lower()
    for host in _SHORTENER_HOSTS:
        if host in lowered:
            return host
    return None


def _check_name(spec: dict, out: list[str]) -> None:
    name = spec.get("name", "")
    if not name or not _NAME_RE.match(name):
        out.append("name must match ^[a-z0-9_]+$ (lowercase letters, digits, underscore)")
    if len(name) > _MAX_NAME_LEN:
        out.append(f"name exceeds {_MAX_NAME_LEN} characters")


def _check_variables(body: str, out: list[str]) -> None:
    nums = [int(n) for n in _VAR_RE.findall(body)]
    if not nums:
        return
    # repeats
    if len(nums) != len(set(nums)):
        out.append("variables must not repeat — sequential {{1}}..{{n}} required")
    # sequential / no gaps
    expected = list(range(1, len(set(nums)) + 1))
    if sorted(set(nums)) != expected:
        out.append("variables must be sequential {{1}}..{{n}} with no gaps")
    # adjacency
    if _ADJACENT_VARS_RE.search(body):
        out.append("adjacent variables ({{1}} {{2}}) need static text between them")


def _check_body(body: str, out: list[str]) -> None:
    if not body:
        out.append("body is required")
        return
    if len(body) > _MAX_BODY_LEN:
        out.append(f"body exceeds {_MAX_BODY_LEN} characters")
    if _TRIPLE_NEWLINE_RE.search(body):
        out.append("body has more than 2 consecutive newlines")
    if body.count("\n") + 1 > _MAX_BODY_LINES:
        out.append(f"body has more than {_MAX_BODY_LINES} lines (may be truncated)")

    host = _has_shortener(body)
    if host:
        out.append(f"body contains a shortened-URL host ({host}) — use full https:// URLs")
    for url in _URL_RE.findall(body):
        if not url.lower().startswith("https://"):
            out.append("body URL must use https://")
            break

    # static-text sufficiency: strip variables, require meaningful static text
    static = _VAR_RE.sub("", body).strip()
    if len(static) < 10:
        out.append("body must contain static text — it is mostly variables")

    _check_variables(body, out)


def _check_footer(spec: dict, out: list[str]) -> None:
    footer = spec.get("footer")
    if not footer:
        return
    if len(footer) > _MAX_FOOTER_LEN:
        out.append(f"footer exceeds {_MAX_FOOTER_LEN} characters")
    if _has_emoji(footer):
        out.append("footer must not contain emoji")
    if _ANY_URL_RE.search(footer):
        out.append("footer must not contain a URL")
    if "{{" in footer:
        out.append("footer must not contain variables")


def _check_header(spec: dict, out: list[str]) -> None:
    header = spec.get("header")
    if not header or header.get("type") != "text":
        return
    text = header.get("text", "")
    if len(text) > _MAX_HEADER_LEN:
        out.append(f"header text exceeds {_MAX_HEADER_LEN} characters")
    if _has_emoji(text):
        out.append("header text must not contain emoji")
    if "\n" in text:
        out.append("header text must not contain a newline")


def _check_buttons(spec: dict, out: list[str]) -> None:
    buttons = spec.get("buttons") or []
    if len(buttons) > _MAX_BUTTONS:
        out.append(f"more than {_MAX_BUTTONS} buttons total")

    url_buttons = [b for b in buttons if b.get("type") == "URL"]
    if len(url_buttons) > _MAX_URL_BUTTONS:
        out.append(f"more than {_MAX_URL_BUTTONS} URL buttons")

    for b in buttons:
        label = b.get("label", "")
        if len(label) > _MAX_BUTTON_LABEL_LEN:
            out.append(f"button label exceeds {_MAX_BUTTON_LABEL_LEN} characters")
        if b.get("type") == "URL":
            url = b.get("url", "")
            if not url.lower().startswith("https://"):
                out.append("URL button must use a full https:// URL")


def _check_opt_out(spec: dict, out: list[str]) -> None:
    footer = (spec.get("footer") or "").upper()
    if "STOP" in footer:
        return
    for b in spec.get("buttons") or []:
        if b.get("type") == "QUICK_REPLY":
            label = b.get("label", "").lower()
            if "stop" in label or "unsubscribe" in label:
                return
    out.append("missing opt-out mechanism")


def lint_template(spec: dict) -> list[str]:
    """Return a list of compliance violation strings (empty = compliant)."""
    out: list[str] = []
    _check_name(spec, out)
    _check_body(spec.get("body", ""), out)
    _check_footer(spec, out)
    _check_header(spec, out)
    _check_buttons(spec, out)
    _check_opt_out(spec, out)
    return out
