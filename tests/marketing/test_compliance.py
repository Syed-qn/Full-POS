"""Unit tests for the WhatsApp template compliance linter.

Pure function `lint_template(spec) -> list[str]`. One assertion per rule.
See plan Task 10 and docs/research/meta-template-compliance.md §3 + §6.
"""
from app.marketing.compliance import lint_template


def clean_spec() -> dict:
    """A fully compliant marketing template spec."""
    return {
        "name": "daily_special_20260606",
        "body": (
            "Hi {{1}}, today's special is {{2}}.\n"
            "Visit us before 9pm to enjoy it fresh.\n"
            "See you soon!"
        ),
        "footer": "Reply STOP to unsubscribe",
        "header": {"type": "text", "text": "Today's Special"},
        "buttons": [
            {"type": "URL", "label": "View Menu", "url": "https://example.com/menu"},
            {"type": "QUICK_REPLY", "label": "Stop"},
        ],
    }


def test_clean_spec_is_compliant():
    assert lint_template(clean_spec()) == []


# --- name rules ----------------------------------------------------------

def test_name_with_uppercase_flagged():
    spec = clean_spec()
    spec["name"] = "Daily_Special"
    assert any("name" in v for v in lint_template(spec))


def test_name_too_long_flagged():
    spec = clean_spec()
    spec["name"] = "a" * 513
    assert any("name" in v for v in lint_template(spec))


# --- body rules ----------------------------------------------------------

def test_body_missing_flagged():
    spec = clean_spec()
    spec["body"] = ""
    assert any("body" in v for v in lint_template(spec))


def test_body_too_long_flagged():
    spec = clean_spec()
    spec["body"] = "{{1}} " + "x" * 1100
    assert any("1024" in v or "body" in v.lower() for v in lint_template(spec))


def test_body_with_bitly_flagged():
    spec = clean_spec()
    spec["body"] = "Order now at bit.ly/abc {{1}}!"
    violations = lint_template(spec)
    assert any("bit.ly" in v or "shortened" in v.lower() for v in violations)


def test_body_with_non_https_url_flagged():
    spec = clean_spec()
    spec["body"] = "Visit http://example.com today {{1}}."
    assert any("https" in v.lower() for v in lint_template(spec))


def test_body_excessive_newlines_flagged():
    spec = clean_spec()
    spec["body"] = "Hi {{1}}.\n\n\nToo many newlines here for you."
    assert any("newline" in v.lower() for v in lint_template(spec))


def test_body_over_five_lines_warns():
    spec = clean_spec()
    spec["body"] = "Hi {{1}}.\nl2\nl3\nl4\nl5\nl6 static text here"
    assert any("line" in v.lower() for v in lint_template(spec))


def test_body_mostly_variables_flagged():
    spec = clean_spec()
    spec["body"] = "{{1}} {{2}}"
    violations = lint_template(spec)
    assert any("static" in v.lower() for v in violations)


# --- variable rules ------------------------------------------------------

def test_body_adjacent_variables_flagged():
    spec = clean_spec()
    spec["body"] = "Hello there {{1}}{{2}} welcome to our restaurant today."
    assert any("adjacent" in v.lower() for v in lint_template(spec))


def test_body_variable_gap_flagged():
    spec = clean_spec()
    spec["body"] = "Hi {{1}}, your table {{3}} is ready and waiting for you now."
    assert any("sequential" in v.lower() or "gap" in v.lower() for v in lint_template(spec))


def test_body_variable_repeat_flagged():
    spec = clean_spec()
    spec["body"] = "Hi {{1}}, your order {{1}} is ready and waiting for you now."
    assert any("repeat" in v.lower() or "sequential" in v.lower() for v in lint_template(spec))


# --- footer rules --------------------------------------------------------

def test_footer_too_long_flagged():
    spec = clean_spec()
    spec["footer"] = "x" * 70  # 70 chars > 60
    assert any("footer" in v.lower() for v in lint_template(spec))


def test_footer_with_emoji_flagged():
    spec = clean_spec()
    spec["footer"] = "Reply STOP \U0001f600"
    assert any("emoji" in v.lower() and "footer" in v.lower() for v in lint_template(spec))


def test_footer_with_url_flagged():
    spec = clean_spec()
    spec["footer"] = "Visit https://example.com STOP"
    assert any("footer" in v.lower() for v in lint_template(spec))


# --- header rules --------------------------------------------------------

def test_header_too_long_flagged():
    spec = clean_spec()
    spec["header"] = {"type": "text", "text": "x" * 70}
    assert any("header" in v.lower() for v in lint_template(spec))


def test_header_with_emoji_flagged():
    spec = clean_spec()
    spec["header"] = {"type": "text", "text": "Special \U0001f600"}
    assert any("header" in v.lower() and "emoji" in v.lower() for v in lint_template(spec))


def test_header_with_newline_flagged():
    spec = clean_spec()
    spec["header"] = {"type": "text", "text": "Today's\nSpecial"}
    assert any("header" in v.lower() for v in lint_template(spec))


# --- button rules --------------------------------------------------------

def test_too_many_url_buttons_flagged():
    spec = clean_spec()
    spec["buttons"] = [
        {"type": "URL", "label": "A", "url": "https://example.com/a"},
        {"type": "URL", "label": "B", "url": "https://example.com/b"},
        {"type": "URL", "label": "C", "url": "https://example.com/c"},
        {"type": "QUICK_REPLY", "label": "Stop"},
    ]
    assert any("url button" in v.lower() for v in lint_template(spec))


def test_too_many_buttons_total_flagged():
    spec = clean_spec()
    spec["buttons"] = [{"type": "QUICK_REPLY", "label": "B%d" % i} for i in range(11)]
    spec["buttons"][0]["label"] = "Stop"
    assert any("10" in v or "button" in v.lower() for v in lint_template(spec))


def test_button_label_too_long_flagged():
    spec = clean_spec()
    spec["buttons"] = [
        {"type": "QUICK_REPLY", "label": "x" * 26},
        {"type": "QUICK_REPLY", "label": "Stop"},
    ]
    assert any("label" in v.lower() for v in lint_template(spec))


def test_url_button_non_https_flagged():
    spec = clean_spec()
    spec["buttons"] = [
        {"type": "URL", "label": "Menu", "url": "http://example.com/menu"},
        {"type": "QUICK_REPLY", "label": "Stop"},
    ]
    assert any("https" in v.lower() for v in lint_template(spec))


# --- opt-out rules -------------------------------------------------------

def test_missing_opt_out_flagged():
    spec = clean_spec()
    spec["footer"] = "Enjoy your meal"
    spec["buttons"] = [
        {"type": "URL", "label": "Menu", "url": "https://example.com/menu"},
    ]
    assert "missing opt-out mechanism" in lint_template(spec)


def test_opt_out_via_footer_stop_is_ok():
    spec = clean_spec()
    spec["buttons"] = [
        {"type": "URL", "label": "Menu", "url": "https://example.com/menu"},
    ]
    # footer already contains STOP
    assert "missing opt-out mechanism" not in lint_template(spec)


def test_opt_out_via_quick_reply_unsubscribe_is_ok():
    spec = clean_spec()
    spec["footer"] = "Enjoy your meal today"
    spec["buttons"] = [
        {"type": "URL", "label": "Menu", "url": "https://example.com/menu"},
        {"type": "QUICK_REPLY", "label": "Unsubscribe"},
    ]
    assert "missing opt-out mechanism" not in lint_template(spec)
