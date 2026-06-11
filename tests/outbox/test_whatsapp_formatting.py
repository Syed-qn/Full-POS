"""WhatsApp shows *single* asterisks as bold; Markdown's **double** asterisks
render as literal characters on the device. to_whatsapp_text() normalizes the
common Markdown an LLM emits."""

from app.outbox.service import to_whatsapp_text


def test_double_asterisk_bold_becomes_single():
    assert to_whatsapp_text("**Grills & Curries**") == "*Grills & Curries*"


def test_bold_inside_a_line_is_converted():
    assert to_whatsapp_text("Try our **Biryani** today!") == "Try our *Biryani* today!"


def test_markdown_header_becomes_bold_line():
    assert to_whatsapp_text("## Menu") == "*Menu*"
    assert to_whatsapp_text("### Drinks\n• Lassi") == "*Drinks*\n• Lassi"


def test_underscores_are_left_alone():
    # We don't convert __double__ underscores, so identifiers/filenames survive.
    assert to_whatsapp_text("call __init__ now") == "call __init__ now"


def test_plain_text_unchanged_and_idempotent():
    plain = "Hi! 👋 Your order is ready 🍽️"
    assert to_whatsapp_text(plain) == plain
    once = to_whatsapp_text("**bold**")
    assert to_whatsapp_text(once) == once  # already single-* stays single-*


def test_multiline_menu_block():
    md = "**Biryani**\n• Chicken Biryani (AED 28)\n**Drinks**\n• Lassi"
    expected = "*Biryani*\n• Chicken Biryani (AED 28)\n*Drinks*\n• Lassi"
    assert to_whatsapp_text(md) == expected
