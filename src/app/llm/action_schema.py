"""Single source of truth for the conversation action (LLM tool) schema (W1).

Every provider (DeepSeek, Claude, Fake) builds its tool from ACTION_SPECS,
validates the model's payload with `validate_required`, and converts a canonical
action + payload into the engine's legacy (action, action_data) shape with
`to_engine_result`. The engine dispatcher (`_dispatch_action`) is unchanged.

Qty semantics are explicit and never overloaded:
  - cart_add.add_qty      -> how many to ADD (delta)
  - cart_set_qty.new_total -> the ABSOLUTE new total
  - cart_remove.remove_qty -> how many to take off (omit = remove the line)
  - items[] entries carry {op: add_delta|set_total|remove_delta, dish_query, qty, note}
"""
from __future__ import annotations

from dataclasses import dataclass

_ALL_PHASES = ("ordering", "address_capture", "awaiting_confirmation", "post_order")


@dataclass(frozen=True)
class ActionSpec:
    phases: tuple[str, ...]
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    qty_field: str | None = None
    requires_one_of: tuple[tuple[str, ...], ...] = ()  # each inner tuple = an OR-group


# Canonical action vocabulary. Field names here are CANONICAL (add_qty/new_total/
# remove_qty/note), distinct from the engine's legacy action_data keys.
ACTION_SPECS: dict[str, ActionSpec] = {
    "cart_add": ActionSpec(
        phases=("ordering", "awaiting_confirmation"),
        optional=("dish_query", "add_qty", "note", "items"),
        qty_field="add_qty",
        requires_one_of=(("dish_query", "items"),),
    ),
    "cart_set_qty": ActionSpec(
        phases=("ordering", "awaiting_confirmation"),
        optional=("dish_query", "new_total", "items"),
        qty_field="new_total",
        requires_one_of=(("dish_query", "items"), ("new_total", "items")),
    ),
    "cart_set_note": ActionSpec(
        phases=("ordering", "awaiting_confirmation"),
        required=("dish_query", "note"),
    ),
    "cart_remove": ActionSpec(
        phases=("ordering", "awaiting_confirmation"),
        optional=("dish_query", "remove_qty", "items"),
        qty_field="remove_qty",
        requires_one_of=(("dish_query", "items"),),
    ),
    "cart_clear": ActionSpec(phases=("ordering",)),
    "checkout_proceed": ActionSpec(phases=("ordering",)),
    "address_save": ActionSpec(
        phases=("address_capture",),
        required=("apt_room", "building", "receiver_name"),
    ),
    "address_location": ActionSpec(phases=("address_capture",)),
    "address_use_saved": ActionSpec(phases=("address_capture",)),
    "address_confirm": ActionSpec(phases=("address_capture",)),
    "confirm_order": ActionSpec(phases=("awaiting_confirmation",)),
    "cancel_order": ActionSpec(
        phases=("ordering", "address_capture", "awaiting_confirmation", "post_order"),
    ),
    "request_modification": ActionSpec(phases=("awaiting_confirmation", "post_order")),
    "status_query": ActionSpec(phases=("post_order",)),
    "menu_show": ActionSpec(phases=("ordering",)),
    "info_answer": ActionSpec(phases=_ALL_PHASES),
    "complaint_explain": ActionSpec(
        phases=("ordering", "awaiting_confirmation", "post_order"),
    ),
    "no_action": ActionSpec(phases=_ALL_PHASES),
}

# Canonical -> engine-legacy action name (the dispatcher contract).
CANON_TO_LEGACY: dict[str, str] = {
    "cart_add": "add_item",
    "cart_set_qty": "update_qty",
    "cart_set_note": "update_qty",
    "cart_remove": "remove_item",
    "cart_clear": "clear_cart",
    "checkout_proceed": "proceed_to_address",
    "address_save": "save_address_text",
    "address_location": "send_location_request",
    "address_use_saved": "use_saved_address",
    "address_confirm": "proceed_to_confirmation",
    "confirm_order": "confirm_order",
    "cancel_order": "cancel_order",
    "request_modification": "request_modification",
    "status_query": "status_query",
    "menu_show": "show_menu",
    "info_answer": "no_action",
    "complaint_explain": "no_action",
    "no_action": "no_action",
}

# Alias kept for callers that want the richer mapping object.
LEGACY_ACTION_MAP = CANON_TO_LEGACY

# Phase -> set of canonical actions allowed in that phase (derived; never hand-edit).
CANON_PHASE_ACTIONS: dict[str, frozenset[str]] = {
    phase: frozenset(a for a, s in ACTION_SPECS.items() if phase in s.phases)
    for phase in _ALL_PHASES
}

# Legacy phase->action map, derived so the engine and the schema can never drift.
LEGACY_PHASE_ACTIONS: dict[str, frozenset[str]] = {
    phase: frozenset(CANON_TO_LEGACY[a] for a in actions)
    for phase, actions in CANON_PHASE_ACTIONS.items()
}

_OPS = ("add_delta", "set_total", "remove_delta")


def build_tool_properties() -> dict:
    """JSON-schema `properties` block shared by every provider's tool."""
    return {
        "action": {
            "type": "string",
            "enum": list(ACTION_SPECS),
            "description": (
                "The single structured action inferred from the customer message. "
                "Pick exactly one. Use namespaced cart_* actions for cart edits."
            ),
        },
        "dish_query": {
            "type": "string",
            "description": "Dish name or number the customer referred to (single-dish edits).",
        },
        "add_qty": {
            "type": "integer",
            "description": "cart_add ONLY: how many units to ADD (a delta). Default 1.",
        },
        "new_total": {
            "type": "integer",
            "description": (
                "cart_set_qty ONLY: the ABSOLUTE new total for the line "
                "(e.g. 'only 1' -> new_total=1, 'make it 4' -> new_total=4). "
                "Never a delta."
            ),
        },
        "remove_qty": {
            "type": "integer",
            "description": (
                "cart_remove ONLY: how many units to take off. OMIT to remove the "
                "whole line ('remove 2 biryani' -> remove_qty=2; 'remove the biryani' "
                "-> omit)."
            ),
        },
        "note": {
            "type": "string",
            "description": "Kitchen note e.g. 'no onion', 'extra spicy' (cart_add / cart_set_note).",
        },
        "items": {
            "type": "array",
            "description": (
                "Multi-dish message: one entry per dish named in the SAME message. "
                "Each entry MUST carry an explicit `op`."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "op": {
                        "type": "string",
                        "enum": list(_OPS),
                        "description": (
                            "add_delta: add this many. set_total: set the line to this "
                            "absolute total. remove_delta: take this many off."
                        ),
                    },
                    "dish_query": {"type": "string", "description": "Dish name or number."},
                    "qty": {"type": "integer", "description": "Units for this op."},
                    "note": {"type": "string", "description": "Kitchen note for this dish."},
                },
                "required": ["op", "dish_query"],
            },
        },
        "apt_room": {"type": "string", "description": "Apartment/room/door number (address_save)."},
        "building": {"type": "string", "description": "Building name or number (address_save)."},
        "receiver_name": {"type": "string", "description": "Receiver name (address_save)."},
        "reply": {
            "type": "string",
            "description": (
                "OPTIONAL non-authoritative tone hint only. The system authors the "
                "real customer-facing text from verified data. Never put prices, "
                "totals, the menu, or order numbers here."
            ),
        },
    }


def build_openai_tool(name: str = "take_action") -> dict:
    """OpenAI / DeepSeek function-tool wrapper."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": (
                "Record the structured action inferred from the customer message. "
                "ALWAYS call this tool, exactly once."
            ),
            "parameters": {
                "type": "object",
                "properties": build_tool_properties(),
                "required": ["action"],
            },
        },
    }


def build_anthropic_tool(name: str = "take_action") -> dict:
    """Anthropic tool-use wrapper (same properties, `input_schema` shape)."""
    return {
        "name": name,
        "description": (
            "Record the structured action inferred from the customer message. "
            "ALWAYS call this tool, exactly once."
        ),
        "input_schema": {
            "type": "object",
            "properties": build_tool_properties(),
            "required": ["action"],
        },
    }


def _present(payload: dict, key: str) -> bool:
    v = payload.get(key)
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, (list, tuple)):
        return len(v) > 0
    return True


def validate_required(action: str, payload: dict) -> list[str]:
    """Return the list of missing mandatory field names. Empty list = OK."""
    spec = ACTION_SPECS.get(action)
    if spec is None:
        return ["action"]
    missing: list[str] = [f for f in spec.required if not _present(payload, f)]
    for group in spec.requires_one_of:
        if not any(_present(payload, f) for f in group):
            # Report the primary field (first member) so callers can check by name.
            # e.g. ("new_total", "items") -> "new_total" signals the quantity is absent.
            missing.append(group[0])
    return missing


def _norm_items(payload: dict, want_op: str) -> list[dict]:
    out: list[dict] = []
    for it in payload.get("items") or []:
        if not isinstance(it, dict):
            continue
        if (it.get("op") or want_op) != want_op:
            continue
        dq = str(it.get("dish_query") or "").strip()
        if not dq:
            continue
        q = it.get("qty")
        qty = int(q) if isinstance(q, (int, float)) and not isinstance(q, bool) else None
        out.append({"dish_query": dq, "qty": qty, "special_note": str(it.get("note") or "")})
    return out


def _empty_action_data() -> dict:
    return {
        "dish_query": "", "qty": None, "special_note": "", "items": [],
        "apt_room": "", "building": "", "receiver_name": "",
    }


def to_engine_result(action: str, payload: dict, *, message: str = "") -> tuple[str, dict]:
    """Translate a canonical action+payload into (engine_action, action_data).

    On a required-field violation, returns ('no_action', {needs_clarification...})
    so the engine emits a deterministic clarification and performs NO mutation.
    """
    if action not in ACTION_SPECS:
        action = "no_action"
    missing = validate_required(action, payload)
    if missing:
        data = _empty_action_data()
        data["needs_clarification"] = True
        data["clarify_action"] = action
        data["missing_fields"] = missing
        return "no_action", data

    legacy = CANON_TO_LEGACY[action]
    data = _empty_action_data()
    data["dish_query"] = str(payload.get("dish_query") or "")

    if action == "cart_add":
        q = payload.get("add_qty")
        data["qty"] = int(q) if isinstance(q, (int, float)) and not isinstance(q, bool) else None
        data["special_note"] = str(payload.get("note") or "")
        data["items"] = _norm_items(payload, "add_delta")
    elif action == "cart_set_qty":
        q = payload.get("new_total")
        data["qty"] = int(q) if isinstance(q, (int, float)) and not isinstance(q, bool) else None
        data["items"] = _norm_items(payload, "set_total")
    elif action == "cart_set_note":
        data["special_note"] = str(payload.get("note") or "")
        data["qty"] = None  # note-only edit; engine keeps existing qty
    elif action == "cart_remove":
        q = payload.get("remove_qty")
        data["qty"] = int(q) if isinstance(q, (int, float)) and not isinstance(q, bool) else None
        data["items"] = _norm_items(payload, "remove_delta")
    elif action == "address_save":
        data["apt_room"] = str(payload.get("apt_room") or "")
        data["building"] = str(payload.get("building") or "")
        data["receiver_name"] = str(payload.get("receiver_name") or "")

    return legacy, data
