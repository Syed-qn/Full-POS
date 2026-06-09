"""Tests for DeepSeekConversationAgent phase-aware prompts and tool schema."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.llm.deepseek import DeepSeekConversationAgent


def _mock_deepseek_response(action: str, reply: str, **extra):
    args = {"action": action, "reply": reply, **extra}
    tc = {"function": {"name": "take_action", "arguments": json.dumps(args)}}
    choice = {"message": {"tool_calls": [tc]}}
    return {"choices": [choice]}


@pytest.fixture
def agent():
    with patch("app.llm.deepseek._get_deepseek_settings", return_value=("fake-key", "deepseek-chat")):
        yield DeepSeekConversationAgent()


async def test_ordering_phase_add_item(agent):
    tool_result = {"action": "add_item", "reply": "Adding biryani!", "dish_query": "biryani", "qty": 2, "special_note": ""}
    with patch("app.llm.deepseek._async_chat_tools", new=AsyncMock(return_value=tool_result)):
        result = await agent.respond(
            restaurant_name="Test Restaurant",
            dialogue_phase="ordering",
            history=[{"role": "user", "content": "2 biryani plz"}],
            context={"menu_text": "110. Biryani AED 22", "cart_summary": ""},
        )

    assert result.action == "add_item"
    assert result.action_data["dish_query"] == "biryani"
    assert result.action_data["qty"] == 2
    assert result.message == "Adding biryani!"


async def test_address_phase_send_location_request(agent):
    tool_result = {"action": "send_location_request", "reply": "Please share your location 📍"}
    with patch("app.llm.deepseek._async_chat_tools", new=AsyncMock(return_value=tool_result)):
        result = await agent.respond(
            restaurant_name="Test Restaurant",
            dialogue_phase="address_capture",
            history=[{"role": "user", "content": "done ordering"}],
            context={
                "cart_summary": "1x Biryani AED 22",
                "saved_address": "",
                "location_received": False,
                "apt_room": "",
                "building": "",
                "receiver_name": "",
                "max_radius_km": 10,
            },
        )

    assert result.action == "send_location_request"


async def test_confirmation_phase_confirm_order(agent):
    tool_result = {"action": "confirm_order", "reply": "Order placed! 🎉"}
    with patch("app.llm.deepseek._async_chat_tools", new=AsyncMock(return_value=tool_result)):
        result = await agent.respond(
            restaurant_name="Test Restaurant",
            dialogue_phase="awaiting_confirmation",
            history=[{"role": "user", "content": "yes confirm"}],
            context={"order_summary": "1x Biryani AED 22\nTotal: AED 22\nCOD\nETA: ~40 min"},
        )

    assert result.action == "confirm_order"


async def test_system_prompt_contains_language_instruction(agent):
    """Verify system prompt mentions all 7 supported languages."""
    captured = {}

    async def fake_chat_tools(api_key, model, system, messages, tools, tool_name, **kwargs):
        captured["system"] = system
        return {"action": "no_action", "reply": "hi"}

    with patch("app.llm.deepseek._async_chat_tools", new=fake_chat_tools):
        await agent.respond(
            restaurant_name="Test",
            dialogue_phase="ordering",
            history=[{"role": "user", "content": "hi"}],
            context={"menu_text": "110. Biryani", "cart_summary": ""},
        )

    system = captured.get("system", "")
    for lang in ["Arabic", "Urdu", "Turkish", "Russian", "Filipino", "Malayalam"]:
        assert lang in system, f"Language {lang} not in system prompt"
