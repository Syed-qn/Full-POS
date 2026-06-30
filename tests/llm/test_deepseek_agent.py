"""Tests for DeepSeekConversationAgent phase-aware prompts and tool schema."""
import json
from unittest.mock import AsyncMock, patch

import pytest

import app.llm.deepseek as ds
from app.llm import action_schema as A
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
    # Mock returns CANONICAL action; respond() must translate to legacy via to_engine_result.
    tool_result = {"action": "cart_add", "reply": "Adding biryani!", "dish_query": "biryani", "add_qty": 2}
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
    # canonical: address_location -> legacy: send_location_request
    tool_result = {"action": "address_location", "reply": "Please share your location 📍"}
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
    # confirm_order is the same in both canonical and legacy schemas
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


# ---------------------------------------------------------------------------
# W1 Task 2: schema-parity tests (RED before implementation, GREEN after)
# ---------------------------------------------------------------------------

def test_ds_tool_is_built_from_shared_schema():
    """_DS_TOOL must be derived from the canonical action_schema module."""
    props = ds._DS_TOOL["function"]["parameters"]["properties"]
    # new_total description must say "absolute" (never a delta)
    assert props["new_total"]["description"].lower().count("absolute") >= 1
    # items entries must carry an explicit op enum
    assert set(props["items"]["items"]["properties"]["op"]["enum"]) == {
        "add_delta", "set_total", "remove_delta",
    }
    # action enum must exactly match the canonical vocabulary
    assert set(ds._DS_TOOL["function"]["parameters"]["properties"]["action"]["enum"]) == set(A.ACTION_SPECS)


@pytest.mark.asyncio
async def test_ds_set_qty_missing_total_yields_no_mutation(monkeypatch):
    """cart_set_qty without new_total must be blocked (no cart mutation)."""
    async def _fake_tools(*a, **k):
        return {"action": "cart_set_qty", "dish_query": "biryani"}  # no new_total

    monkeypatch.setattr(ds, "_async_chat_tools", _fake_tools)
    agent = ds.DeepSeekConversationAgent.__new__(ds.DeepSeekConversationAgent)
    agent._api_key, agent._model = "k", "m"
    res = await agent.respond(
        restaurant_name="R", dialogue_phase="ordering", history=[], context={},
    )
    assert res.action == "no_action"
    assert res.action_data["needs_clarification"] is True


@pytest.mark.asyncio
async def test_ds_set_qty_absolute(monkeypatch):
    """cart_set_qty with new_total maps to legacy update_qty with correct qty."""
    async def _fake_tools(*a, **k):
        return {"action": "cart_set_qty", "dish_query": "biryani", "new_total": 1}

    monkeypatch.setattr(ds, "_async_chat_tools", _fake_tools)
    agent = ds.DeepSeekConversationAgent.__new__(ds.DeepSeekConversationAgent)
    agent._api_key, agent._model = "k", "m"
    res = await agent.respond(
        restaurant_name="R", dialogue_phase="ordering", history=[], context={},
    )
    assert res.action == "update_qty"
    assert res.action_data["qty"] == 1
