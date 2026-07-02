import pytest
from app.llm.fake import FakeConversationAgent, FakeExtractor
from app.llm.port import DishDraft, UploadedFile

pytestmark = pytest.mark.asyncio


async def _closing(text: str):
    agent = FakeConversationAgent()
    return await agent.respond(
        restaurant_name="Test",
        dialogue_phase="ordering",
        history=[
            {"role": "assistant", "content": "1x Lemon mint added! Anything else?"},
            {"role": "user", "content": text},
        ],
        context={"cart_summary": "1x Lemon mint"},
    )


@pytest.mark.parametrize("text", [
    "No that’s all",          # curly apostrophe (U+2019) — production keyboard
    "That’s all",
    "thats all can’t you understand",
    "no",
])
async def test_fake_closing_variants_proceed(text):
    result = await _closing(text)
    assert result.action == "proceed_to_address"


async def test_fake_extractor_returns_drafts():
    fake = FakeExtractor()
    files = [UploadedFile(filename="menu.jpg", content=b"\xff\xd8", mime="image/jpeg")]
    drafts = await fake.extract_menu(files)
    assert len(drafts) >= 2
    assert all(isinstance(d, DishDraft) for d in drafts)
    assert drafts[0].dish_number == 110
    assert drafts[0].name == "Chicken Biryani"


async def test_fake_extractor_canned_override():
    canned = [DishDraft(dish_number=1, name="Tea", price_aed="2.00")]
    fake = FakeExtractor(canned=canned)
    drafts = await fake.extract_menu([])
    assert drafts == canned


async def test_fake_closing_empty_cart_does_not_proceed():
    agent = FakeConversationAgent()
    result = await agent.respond(
        restaurant_name="Test",
        dialogue_phase="ordering",
        history=[{"role": "user", "content": "no"}],
        context={"cart_summary": ""},
    )
    assert result.action != "proceed_to_address"


async def test_fake_agent_new_interface():
    from app.llm.fake import FakeConversationAgent
    agent = FakeConversationAgent()
    result = await agent.respond(
        restaurant_name="Test",
        dialogue_phase="ordering",
        history=[{"role": "user", "content": "hi"}],
        context={"menu_text": "110. Biryani AED 22", "cart_summary": ""},
    )
    assert result.action in {"no_action", "add_item", "proceed_to_address"}
    assert isinstance(result.message, str)
    assert isinstance(result.action_data, dict)


# ---------------------------------------------------------------------------
# Task 4 (W1): schema-faithful Fake — TDD negative fixtures + canonical routing
# ---------------------------------------------------------------------------

async def test_fake_only_one_is_set_qty_absolute():
    """'only 1 chicken biryani' must emit update_qty (cart_set_qty), NOT add_item."""
    agent = FakeConversationAgent()
    res = await agent.respond(
        restaurant_name="R", dialogue_phase="ordering",
        history=[{"role": "user", "content": "only 1 chicken biryani"}],
        context={"cart_summary": "2x Chicken Biryani"},
    )
    assert res.action == "update_qty"
    assert res.action_data["qty"] == 1


async def test_fake_make_it_n_is_set_qty():
    """'make it 4 biryani' must emit update_qty (cart_set_qty), NOT add_item."""
    agent = FakeConversationAgent()
    res = await agent.respond(
        restaurant_name="R", dialogue_phase="ordering",
        history=[{"role": "user", "content": "make it 4 biryani"}],
        context={"cart_summary": "1x Biryani"},
    )
    assert res.action == "update_qty"
    assert res.action_data["qty"] == 4


async def test_fake_plain_add_is_delta():
    """'2 biryani' must emit add_item (cart_add delta), NOT update_qty."""
    agent = FakeConversationAgent()
    res = await agent.respond(
        restaurant_name="R", dialogue_phase="ordering",
        history=[{"role": "user", "content": "2 biryani"}], context={},
    )
    assert res.action == "add_item"
    assert res.action_data["qty"] == 2


async def test_fake_emits_validatable_payloads_only():
    """Every Fake output must be a clean engine-legacy result, never a raw canonical dict."""
    agent = FakeConversationAgent()
    res = await agent.respond(
        restaurant_name="R", dialogue_phase="ordering",
        history=[{"role": "user", "content": "hi"}], context={},
    )
    assert res.action in {"no_action", "show_menu"}


# Confirm-phase false-positive guards (R-045)

async def test_fake_confirm_phase_address_not_cart_add():
    """'address' contains 'add' as substring — must NOT yield add_item at confirm phase."""
    agent = FakeConversationAgent()
    res = await agent.respond(
        restaurant_name="R", dialogue_phase="awaiting_confirmation",
        history=[{"role": "user", "content": "what is my address?"}],
        context={},
    )
    assert res.action != "add_item"


async def test_fake_confirm_phase_dont_add_more_not_cart_add():
    """'don't add more' is a refusal, not a cart_add command."""
    agent = FakeConversationAgent()
    res = await agent.respond(
        restaurant_name="R", dialogue_phase="awaiting_confirmation",
        history=[{"role": "user", "content": "don't add more"}],
        context={},
    )
    assert res.action != "add_item"
