import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.llm.claude import ClaudeExtractor
from app.llm.port import UploadedFile

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
