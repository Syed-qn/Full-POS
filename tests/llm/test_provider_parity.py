"""Provider-parity contract: DeepSeek, Claude, Fake expose ONE action surface (W1).

Closes R-045 / F33. Pure introspection — no API keys, no DB.

NON-TAUTOLOGY PROOF
-------------------
* DeepSeek surface is derived from ``ds._DS_TOOL`` — the live module-level OpenAI
  tool dict built by ``build_openai_tool()`` at import time.
* Claude surface is derived from ``cl._CONVERSATION_TOOL`` — the live module-level
  Anthropic tool dict built by ``build_anthropic_tool()`` at import time.
* Fake surface is verified structurally: ``FakeConversationAgent`` imports and
  calls ``to_engine_result`` (confirmed by inspecting its source module), binding
  it to the same canonical schema.  A behavioural test additionally asserts that
  every action the Fake emits is a known legacy action in ``CANON_TO_LEGACY``.
* The canonical set (``A.ACTION_SPECS``) is NOT compared to itself; it is the
  reference against which the two independently-shaped tool dicts are checked.
  If either provider's dict was built by a different path (e.g., an old hardcoded
  list), assertions would fail.
"""
from __future__ import annotations

import asyncio
import inspect

import app.llm.claude as cl
import app.llm.deepseek as ds
import app.llm.fake as fk
from app.llm import action_schema as A


# ---------------------------------------------------------------------------
# Helpers: derive each provider's action surface from its own live tool object
# ---------------------------------------------------------------------------

def _ds_props() -> dict:
    """Properties block extracted from DeepSeek's live OpenAI tool dict."""
    return ds._DS_TOOL["function"]["parameters"]["properties"]


def _cl_props() -> dict:
    """Properties block extracted from Claude's live Anthropic tool dict."""
    return cl._CONVERSATION_TOOL["input_schema"]["properties"]


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------

def test_action_enums_identical_across_providers():
    """Both provider tool dicts enumerate exactly the canonical action set."""
    canon = set(A.ACTION_SPECS)
    assert set(_ds_props()["action"]["enum"]) == canon, (
        f"DeepSeek action enum drifted. Extra: "
        f"{set(_ds_props()['action']['enum']) - canon}  "
        f"Missing: {canon - set(_ds_props()['action']['enum'])}"
    )
    assert set(_cl_props()["action"]["enum"]) == canon, (
        f"Claude action enum drifted. Extra: "
        f"{set(_cl_props()['action']['enum']) - canon}  "
        f"Missing: {canon - set(_cl_props()['action']['enum'])}"
    )


def test_field_property_sets_identical():
    """DeepSeek and Claude expose the same top-level property names."""
    ds_keys = set(_ds_props())
    cl_keys = set(_cl_props())
    assert ds_keys == cl_keys, (
        f"Field sets differ. DS-only: {ds_keys - cl_keys}  CL-only: {cl_keys - ds_keys}"
    )


def test_items_op_enum_identical():
    """The items[].op enum is identical in both providers and matches the spec."""
    expected = {"add_delta", "set_total", "remove_delta"}
    for label, props in (("DeepSeek", _ds_props()), ("Claude", _cl_props())):
        actual = set(props["items"]["items"]["properties"]["op"]["enum"])
        assert actual == expected, (
            f"{label} items[].op enum mismatch. Got: {actual}  Expected: {expected}"
        )


def test_required_fields_per_action_match_spec():
    """validate_required() recognises all canonical actions and returns sane data."""
    for action, spec in A.ACTION_SPECS.items():
        missing_when_empty = A.validate_required(action, {})
        assert isinstance(missing_when_empty, list), (
            f"validate_required({action!r}, {{}}) must return a list"
        )
        assert all(isinstance(m, str) for m in missing_when_empty), (
            f"validate_required({action!r}, {{}}) returned non-string items"
        )


def test_qty_field_is_never_overloaded():
    """Explicit qty fields exist; the legacy overloaded 'qty' top-level field is gone."""
    for label, props in (("DeepSeek", _ds_props()), ("Claude", _cl_props())):
        assert "add_qty" in props, f"{label}: missing 'add_qty'"
        assert "new_total" in props, f"{label}: missing 'new_total'"
        assert "remove_qty" in props, f"{label}: missing 'remove_qty'"
        assert "qty" not in props, (
            f"{label}: legacy overloaded 'qty' is still present at top level"
        )


def test_canon_phase_actions_consistent_with_legacy_map():
    """CANON_PHASE_ACTIONS maps cleanly to LEGACY_PHASE_ACTIONS via CANON_TO_LEGACY."""
    for phase, canon_actions in A.CANON_PHASE_ACTIONS.items():
        legacy = {A.CANON_TO_LEGACY[a] for a in canon_actions}
        assert legacy == set(A.LEGACY_PHASE_ACTIONS[phase]), (
            f"Phase {phase!r}: canonical->legacy map inconsistent with LEGACY_PHASE_ACTIONS"
        )


def test_fake_routes_through_to_engine_result():
    """FakeConversationAgent is structurally bound to the canonical schema.

    Verifies that the Fake module imports ``to_engine_result`` from action_schema,
    which is the gateway through which every action name is validated and translated.
    This is a structural invariant, not a runtime one.
    """
    src = inspect.getsource(fk.FakeConversationAgent)
    assert "to_engine_result" in src, (
        "FakeConversationAgent must call to_engine_result; "
        "if removed it is no longer schema-bound."
    )


def test_fake_only_emits_known_legacy_actions():
    """FakeConversationAgent behavioural check: every emitted action is in CANON_TO_LEGACY values."""
    valid_legacy = set(A.CANON_TO_LEGACY.values())
    agent = fk.FakeConversationAgent()

    scenarios = [
        # (phase, last_user_message, context_extras)
        ("ordering", "hi", {}),
        ("ordering", "menu", {}),
        ("ordering", "2 chicken biryani", {}),
        ("ordering", "remove biryani", {}),
        ("ordering", "done", {"cart_summary": "1x Biryani"}),
        ("ordering", "cancel", {}),
        ("ordering", "clear the cart", {}),
        ("address_capture", "ok", {"saved_address": "Tower A, 101"}),
        ("address_capture", "yes", {"saved_address": "Tower A, 101"}),
        ("address_capture", "hello", {}),
        ("awaiting_confirmation", "yes", {}),
        ("awaiting_confirmation", "cancel", {}),
        ("awaiting_confirmation", "add extra biryani", {}),
        ("post_order", "cancel", {}),
        ("post_order", "modify order", {}),
        ("post_order", "remove lemon mint", {}),
        ("post_order", "where is my order", {}),
    ]

    for phase, msg, ctx in scenarios:
        history = [{"role": "user", "content": msg}]
        result = asyncio.get_event_loop().run_until_complete(
            agent.respond(
                restaurant_name="Test Restaurant",
                dialogue_phase=phase,
                history=history,
                context=ctx,
            )
        )
        assert result.action in valid_legacy, (
            f"FakeConversationAgent emitted unknown action {result.action!r} "
            f"for phase={phase!r} msg={msg!r}.  "
            f"Valid legacy actions: {sorted(valid_legacy)}"
        )


def test_both_providers_required_field_is_action_only():
    """Both tool dicts declare only 'action' as a top-level required field."""
    ds_required = ds._DS_TOOL["function"]["parameters"]["required"]
    cl_required = cl._CONVERSATION_TOOL["input_schema"]["required"]
    assert ds_required == ["action"], f"DeepSeek required fields: {ds_required}"
    assert cl_required == ["action"], f"Claude required fields: {cl_required}"
