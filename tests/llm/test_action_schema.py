"""Contract tests for the canonical conversation action schema (W1)."""
from __future__ import annotations

from app.llm import action_schema as A


def test_specs_cover_every_canonical_action():
    expected = {
        "cart_add", "cart_set_qty", "cart_set_note", "cart_remove", "cart_clear",
        "order_line_remove", "order_line_set_qty", "order_modify_confirm",
        "checkout_proceed", "address_save", "address_location", "address_use_saved",
        "address_confirm", "confirm_order", "cancel_order", "request_modification",
        "status_query", "menu_show", "info_answer", "complaint_explain", "no_action",
    }
    assert set(A.ACTION_SPECS) == expected


def test_every_action_maps_to_a_known_engine_action():
    legacy = {
        "add_item", "update_qty", "remove_item", "clear_cart", "proceed_to_address",
        "save_address_text", "send_location_request", "use_saved_address",
        "proceed_to_confirmation", "confirm_order", "cancel_order",
        "request_modification", "status_query", "show_menu", "no_action",
        "confirm_line_edit",
    }
    for canon in A.ACTION_SPECS:
        assert A.CANON_TO_LEGACY[canon] in legacy, canon


def test_phase_actions_derived_and_nonempty():
    for phase in ("ordering", "address_capture", "awaiting_confirmation", "post_order"):
        assert A.CANON_PHASE_ACTIONS[phase], phase
        assert "no_action" in A.CANON_PHASE_ACTIONS[phase]


def test_qty_semantics_are_explicit_never_overloaded():
    # cart_add carries a DELTA field; cart_set_qty carries an ABSOLUTE field; no
    # single shared `qty` key exists in either required/optional field set.
    assert A.ACTION_SPECS["cart_add"].qty_field == "add_qty"
    assert A.ACTION_SPECS["cart_set_qty"].qty_field == "new_total"
    assert A.ACTION_SPECS["cart_remove"].qty_field == "remove_qty"
    assert A.ACTION_SPECS["order_line_remove"].qty_field == "remove_qty"
    assert A.ACTION_SPECS["order_line_set_qty"].qty_field == "new_total"
    for spec in A.ACTION_SPECS.values():
        assert "qty" not in spec.required
        assert "qty" not in spec.optional


def test_items_op_enum_present_in_tool_properties():
    props = A.build_tool_properties()
    item_props = props["items"]["items"]["properties"]
    assert set(item_props["op"]["enum"]) == {"add_delta", "set_total", "remove_delta"}


def test_validate_required_flags_missing_new_total():
    missing = A.validate_required("cart_set_qty", {"dish_query": "biryani"})
    assert "new_total" in missing


def test_validate_required_accepts_complete_payload():
    assert A.validate_required("cart_set_qty", {"dish_query": "biryani", "new_total": 1}) == []


def test_to_engine_result_set_qty_is_absolute():
    action, data = A.to_engine_result("cart_set_qty", {"dish_query": "biryani", "new_total": 1})
    assert action == "update_qty"
    assert data["qty"] == 1
    assert data["items"] == []


def test_to_engine_result_add_is_delta():
    action, data = A.to_engine_result("cart_add", {"dish_query": "biryani", "add_qty": 2})
    assert action == "add_item"
    assert data["qty"] == 2


def test_to_engine_result_missing_required_yields_clarification_no_mutation():
    action, data = A.to_engine_result("cart_set_qty", {"dish_query": "biryani"})
    assert action == "no_action"
    assert data["needs_clarification"] is True
    assert data["clarify_action"] == "cart_set_qty"


def test_to_engine_result_order_line_remove_maps_to_remove_item():
    action, data = A.to_engine_result(
        "order_line_remove", {"dish_query": "lemon mint", "remove_qty": 1},
    )
    assert action == "remove_item"
    assert data["qty"] == 1


def test_to_engine_result_splits_items_by_op():
    action, data = A.to_engine_result(
        "cart_set_qty",
        {"items": [{"op": "set_total", "dish_query": "biryani", "qty": 2}]},
    )
    assert action == "update_qty"
    assert data["items"] == [{"dish_query": "biryani", "qty": 2, "special_note": ""}]
