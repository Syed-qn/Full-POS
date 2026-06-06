import json
from unittest.mock import AsyncMock, MagicMock

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


async def test_claude_extractor_parses_tool_response():
    block = MagicMock()
    block.type = "tool_use"
    block.input = RAW
    response = MagicMock()
    response.content = [block]

    extractor = ClaudeExtractor()
    extractor._client = MagicMock()
    extractor._client.messages.create = AsyncMock(return_value=response)

    files = [UploadedFile(filename="m.jpg", content=b"\xff\xd8\xff", mime="image/jpeg")]
    drafts = await extractor.extract_menu(files)

    assert len(drafts) == 2
    assert drafts[0].dish_number == 110
    assert str(drafts[0].price_aed) == "22.00"
    assert drafts[1].dish_number is None  # flagged for manual entry downstream

    call = extractor._client.messages.create.call_args
    sent = json.dumps(call.kwargs)
    assert "base64" in sent  # image attached
