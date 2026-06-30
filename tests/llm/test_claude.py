import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.llm.claude as cl
import app.llm.deepseek as ds
from app.llm.claude import ClaudeConversationAgent, ClaudeExtractor
from app.llm.port import ConversationAgentResult, UploadedFile


# ---------------------------------------------------------------------------
# W1 Task 3: tool-schema parity tests
# ---------------------------------------------------------------------------

def test_claude_tool_action_enum_matches_deepseek():
    c = set(cl._CONVERSATION_TOOL["input_schema"]["properties"]["action"]["enum"])
    d = set(ds._DS_TOOL["function"]["parameters"]["properties"]["action"]["enum"])
    assert c == d


def test_claude_tool_has_items_op_and_note():
    props = cl._CONVERSATION_TOOL["input_schema"]["properties"]
    assert "note" in props
    assert set(props["items"]["items"]["properties"]["op"]["enum"]) == {
        "add_delta", "set_total", "remove_delta",
    }


async def test_claude_respond_translates_canonical_to_legacy():
    """Round-trip: Claude returns canonical 'cart_add' -> respond() yields legacy 'add_item'."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = "take_action"
    block.input = {
        "action": "cart_add",
        "dish_query": "biryani",
        "add_qty": 2,
        "reply": "Added!",
    }
    response = MagicMock()
    response.content = [block]

    agent = ClaudeConversationAgent.__new__(ClaudeConversationAgent)
    agent._model = "claude-opus-4-8"
    agent._client = MagicMock()
    agent._client.messages.create = AsyncMock(return_value=response)

    result = await agent.respond(
        restaurant_name="Test",
        dialogue_phase="ordering",
        history=[{"role": "user", "content": "2 biryani"}],
        context={"menu_text": "1. Biryani AED 22", "cart_summary": "empty"},
    )

    assert isinstance(result, ConversationAgentResult)
    assert result.action == "add_item", (
        f"respond() must translate canonical 'cart_add' -> legacy 'add_item', got {result.action!r}"
    )

RAW = {
    "dishes": [
        {"dish_number": 110, "name": "Chicken Biryani", "price_aed": "22.00",
         "category": "Rice", "description": "Spiced rice"},
        {"dish_number": None, "name": "Mystery Dish", "price_aed": None,
         "category": None, "description": None},
    ]
}


def _make_extractor(block_input=None, stop_reason="tool_use"):
    block = MagicMock()
    block.type = "tool_use"
    block.input = RAW if block_input is None else block_input
    response = MagicMock()
    response.content = [block]
    response.stop_reason = stop_reason

    extractor = ClaudeExtractor()
    extractor._client = MagicMock()
    extractor._client.messages.create = AsyncMock(return_value=response)
    return extractor


async def test_claude_extractor_parses_tool_response():
    extractor = _make_extractor(stop_reason="tool_use")

    files = [UploadedFile(filename="m.jpg", content=b"\xff\xd8\xff", mime="image/jpeg")]
    drafts = await extractor.extract_menu(files)

    assert len(drafts) == 2
    assert drafts[0].dish_number == 110
    assert str(drafts[0].price_aed) == "22.00"
    assert drafts[1].dish_number is None  # flagged for manual entry downstream

    call = extractor._client.messages.create.call_args
    sent = json.dumps(call.kwargs)
    assert "base64" in sent  # image attached


async def test_truncation_raises():
    extractor = _make_extractor(stop_reason="max_tokens")

    files = [UploadedFile(filename="m.jpg", content=b"\xff\xd8\xff", mime="image/jpeg")]
    with pytest.raises(RuntimeError, match="truncated"):
        await extractor.extract_menu(files)


async def test_unsupported_mime_rejected():
    extractor = _make_extractor()

    files = [UploadedFile(filename="m.tiff", content=b"\x49\x49", mime="image/tiff")]
    with pytest.raises(ValueError, match="Unsupported"):
        await extractor.extract_menu(files)


async def test_pdf_sent_as_document_block():
    """A PDF menu is attached as a base64 document (Claude reads it natively) —
    never decoded to text."""
    extractor = _make_extractor()
    files = [UploadedFile(filename="menu.pdf", content=b"%PDF-1.4 binary", mime="application/pdf")]
    drafts = await extractor.extract_menu(files)
    assert len(drafts) == 2
    call = extractor._client.messages.create.call_args
    blocks = call.kwargs["messages"][0]["content"]
    assert any(b.get("type") == "document" for b in blocks)


async def test_text_menu_accepted_as_text_block():
    """A plain-text menu is included verbatim as a text block (not rejected)."""
    extractor = _make_extractor()
    files = [UploadedFile(
        filename="menu.txt",
        content="110 Chicken Biryani AED 22\n201 Mutton Karahi AED 35".encode(),
        mime="text/plain",
    )]
    drafts = await extractor.extract_menu(files)
    assert len(drafts) == 2  # parsed from the mocked tool response
    call = extractor._client.messages.create.call_args
    sent = json.dumps(call.kwargs)
    assert "Chicken Biryani" in sent  # the menu text reached the model


async def test_empty_files_rejected():
    extractor = _make_extractor()

    with pytest.raises(ValueError):
        await extractor.extract_menu([])


async def test_missing_dishes_key_raises():
    extractor = _make_extractor(block_input={}, stop_reason="tool_use")

    files = [UploadedFile(filename="m.jpg", content=b"\xff\xd8\xff", mime="image/jpeg")]
    with pytest.raises(RuntimeError, match="dishes"):
        await extractor.extract_menu(files)


async def test_malformed_dish_raises_runtime_error():
    malformed_input = {"dishes": [{"name": ["not", "a", "string"]}]}
    extractor = _make_extractor(block_input=malformed_input, stop_reason="tool_use")
    files = [UploadedFile(filename="m.jpg", content=b"\xff\xd8\xff", mime="image/jpeg")]
    with pytest.raises(RuntimeError, match="Malformed dish"):
        await extractor.extract_menu(files)
