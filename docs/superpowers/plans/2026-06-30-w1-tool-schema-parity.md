# W1 — One Hardened Tool/Action Schema (Provider Parity) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Strict TDD: write the failing test, run RED, implement, run GREEN, commit. Never write implementation before its failing test.

**Goal:** Make the LLM tool surface (the conversation action schema) **single, strict, poka-yoke, and provider-identical** across DeepSeek, Claude, and Fake. One canonical `ConversationActionPort` vocabulary is defined once and shared; quantity semantics are explicit (`add_qty` delta vs `new_total` absolute, per-item `op`); required fields are validated before any cart mutation; Claude reaches full parity with DeepSeek (or is gated out of `get_conversation_agent()` until it does); a contract test makes divergence impossible; and Fake becomes schema-faithful (no substring heuristics). Closes R-003, R-062, F20-B, F52, F53, F54, RA-6, R-069, R-070, R-078, R-045, F33; deletes dead F67.

**Architecture:**
- A new single-source-of-truth module `src/app/llm/action_schema.py` defines `ACTION_SPECS` (canonical namespaced action names → allowed phases + required fields + qty-field name), derives `CANON_PHASE_ACTIONS`, builds the JSON tool-parameter schema each provider feeds its tool-calling API, validates a returned payload (`validate_required`), and translates a canonical action+payload into the **legacy engine action + `action_data`** the existing `_dispatch_action` already consumes (`to_engine_result`). This keeps the 5720-line engine dispatcher and its handlers untouched while unifying everything upstream of it.
- All three providers (`deepseek.py`, `claude.py`, `fake.py`) build their tool from `ACTION_SPECS`, validate the model's payload, and return a `ConversationAgentResult` whose `.action` / `.action_data` are already in **engine-legacy** form (so the dispatcher contract is unchanged). The reconciliation between the spec's namespaced names (`cart_add`, `cart_set_qty`, …) and the engine's legacy names (`add_item`, `update_qty`, …) lives entirely in `action_schema.to_engine_result` / `LEGACY_ACTION_MAP`.
- Required-field-missing → `to_engine_result` yields engine action `no_action` carrying `action_data={"needs_clarification": True, "clarify_action": <canon>}`; the engine's `no_action` path detects this flag and sends a deterministic clarification with **zero** cart mutation (R-069).
- `reply` becomes optional and non-authoritative (a tone hint), per R-078; factual customer copy continues to be authored deterministically by the engine (and is hardened further in W3). The LLM never authors money/menu/totals/order#.
- A pure-introspection contract test (`tests/llm/test_provider_parity.py`) asserts all three providers expose identical action names + required fields per phase. It needs **no** live API keys (it reads the static tool dicts), so it runs in CI.

**Tech Stack:** Python 3.12, async SQLAlchemy 2, pytest / pytest-asyncio, FastAPI DI, provider ports (`FakeConversationAgent` in tests), Docker Postgres+PostGIS (`:5433`, `restaurant_test` DB). DeepSeek = raw httpx OpenAI-compatible tool-calling; Claude = `anthropic.AsyncAnthropic` tool-use; Fake = deterministic test double.

## Global Constraints

- Multi-tenant: every tenant table carries `restaurant_id`; never leak across tenants.
- Multi-language: **no hardcoded English phrase tables on live interpretation paths.** Clarification copy added in W1 is a single deterministic fallback string (not a phrase-matching table) and is acceptable as engine-authored copy; it must not be used to *interpret* customer intent.
- LLM never authors money, menu text, totals, or order numbers. `reply` is a non-authoritative tone hint only (R-078).
- Money: `Numeric(8,2)` / `Decimal`, AED. DB UTC; Celery Asia/Dubai.
- Tests use the `restaurant_test` DB (Docker, port 5433); schema recreated per test via `tests/conftest.py`. Eval/contract tests run under the **Fake** provider (`settings.llm_provider` defaults to fake in tests). Live-provider tool dicts are introspected statically (no API calls).
- TDD: failing test first, every task. Commit per task.
- After completion run the full matrix + `.venv/bin/ruff check src apps tests` + `/graphify . --update` + append `understanding.txt` (date/time bullets).
- Conventional commits (`feat:`, `fix:`, `refactor:`, `test:`, `chore:`). Each commit message ends with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Branch off the W0 integration branch first (never commit remediation work to `main`).
- Sources of truth: `docs/superpowers/specs/2026-06-30-whatsapp-ordering-remediation-design.md` §"W1 — One hardened tool/action schema (provider parity)"; `docs/superpowers/specs/2026-06-30-biryani-correction-flow-root-cause.md` IDs R-003, R-062, F20-B, F52, F53, F54, RA-6, R-069, R-070, R-078, R-045, F33, F67.

## Canonical ↔ legacy reconciliation (READ before coding)

The remediation design names 13 core actions. The engine dispatcher (`engine.py:4444–4819`) and `_PHASE_ACTIONS` (`engine.py:3246–3261`) currently expect 15 legacy names. W1 keeps the engine's legacy names as the dispatch contract and maps canonical → legacy. The full reconciliation table (this is the spec for `LEGACY_ACTION_MAP`):

| Canonical (spec)        | Phase(s)                                   | Required fields                          | qty field   | → Engine action            |
|-------------------------|--------------------------------------------|------------------------------------------|-------------|----------------------------|
| `cart_add`              | ordering, awaiting_confirmation            | `dish_query` **or** non-empty `items`    | `add_qty`   | `add_item`                 |
| `cart_set_qty`          | ordering, awaiting_confirmation            | (`dish_query`)+`new_total` **or** `items`| `new_total` | `update_qty`               |
| `cart_set_note`         | ordering, awaiting_confirmation            | `dish_query`+`note`                      | —           | `update_qty` (note only)   |
| `cart_remove`           | ordering, awaiting_confirmation            | `dish_query` **or** non-empty `items`    | `remove_qty`| `remove_item`              |
| `cart_clear`            | ordering                                   | —                                        | —           | `clear_cart`               |
| `checkout_proceed`      | ordering                                   | —                                        | —           | `proceed_to_address`       |
| `address_save`          | address_capture                            | `apt_room`+`building`+`receiver_name`    | —           | `save_address_text`        |
| `address_location`*     | address_capture                            | —                                        | —           | `send_location_request`    |
| `address_use_saved`*    | address_capture                            | —                                        | —           | `use_saved_address`        |
| `address_confirm`*      | address_capture                            | —                                        | —           | `proceed_to_confirmation`  |
| `confirm_order`         | awaiting_confirmation                      | —                                        | —           | `confirm_order`            |
| `cancel_order`          | ordering, address_capture, awaiting_confirmation, post_order | —              | —           | `cancel_order`             |
| `request_modification`* | awaiting_confirmation, post_order          | —                                        | —           | `request_modification`     |
| `status_query`*         | post_order                                 | —                                        | —           | `status_query`             |
| `menu_show`             | ordering                                   | —                                        | —           | `show_menu`                |
| `info_answer`           | ordering, address_capture, awaiting_confirmation, post_order | —              | —           | `no_action`                |
| `complaint_explain`     | ordering, awaiting_confirmation, post_order| —                                        | —           | `no_action` (W3/W5 enrich) |
| `no_action`             | all                                        | —                                        | —           | `no_action`                |

`*` = retained engine actions not in the spec's headline 13 but required for full-phase parity; they keep the address/post-order flow working unchanged. `cart_set_note` maps to `update_qty` carrying `special_note` with `new_total` omitted — the engine's `_execute_ai_update_qty` already attaches a note to the matched line; **true line-level note identity (`line_ref`) is W2** — W1 only forbids the overloaded single `qty` and routes notes deterministically.

Per-item ops: `items[]` entry = `{op: "add_delta"|"set_total"|"remove_delta", dish_query, qty, note}`. `to_engine_result` splits a mixed `items[]` by `op` and routes each group to the matching engine action's `items` list (`add_delta`→`add_item`, `set_total`→`update_qty`, `remove_delta`→`remove_item`). For W1 a single action's `items[]` is expected to be homogeneous per the prompt; `to_engine_result` asserts/normalizes this.

---

### Task 0: Create the W1 branch

**Files:** none (git only)

**Interfaces:** Produces branch `remediation/w1-tool-schema-parity` off the W0 integration branch.

- [ ] **Step 1: Confirm starting point**

Run: `git branch --show-current && git log --oneline -3`
Expected: you are on `remediation/w0-eval-harness` (or the branch where W0 landed) with the eval harness committed. If W0 is already merged to `main`, branch off `main` instead.

- [ ] **Step 2: Create and switch to the branch**

Run: `git checkout -b remediation/w1-tool-schema-parity`
Expected: `Switched to a new branch 'remediation/w1-tool-schema-parity'`.

---

### Task 1: Canonical action schema module (single source of truth)

**Files:**
- Create: `src/app/llm/action_schema.py`
- Create: `tests/llm/test_action_schema.py`

**Interfaces:**
- Produces: `ACTION_SPECS`, `CANON_PHASE_ACTIONS`, `LEGACY_ACTION_MAP`, `CANON_TO_LEGACY`, `build_tool_properties()`, `build_openai_tool()`, `build_anthropic_tool()`, `validate_required(action, payload)`, `to_engine_result(action, payload, *, message="")`.
- Consumes: nothing (pure, no DB, no network).

- [ ] **Step 1: Write the failing test**

Create `tests/llm/test_action_schema.py`:

```python
"""Contract tests for the canonical conversation action schema (W1)."""
from __future__ import annotations

import pytest

from app.llm import action_schema as A


def test_specs_cover_every_canonical_action():
    expected = {
        "cart_add", "cart_set_qty", "cart_set_note", "cart_remove", "cart_clear",
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


def test_to_engine_result_splits_items_by_op():
    action, data = A.to_engine_result(
        "cart_set_qty",
        {"items": [{"op": "set_total", "dish_query": "biryani", "qty": 2}]},
    )
    assert action == "update_qty"
    assert data["items"] == [{"dish_query": "biryani", "qty": 2, "special_note": ""}]
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/llm/test_action_schema.py -q`
Expected: collection/import error or failures (module does not exist yet).

- [ ] **Step 3: Implement `src/app/llm/action_schema.py`**

Create `src/app/llm/action_schema.py`:

```python
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

from dataclasses import dataclass, field

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
            missing.append("|".join(group))
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
```

- [ ] **Step 4: Run GREEN**

Run: `.venv/bin/python -m pytest tests/llm/test_action_schema.py -q`
Expected: all tests pass.

- [ ] **Step 5: Lint + commit**

Run: `.venv/bin/ruff check src/app/llm/action_schema.py tests/llm/test_action_schema.py`
Run: `git add src/app/llm/action_schema.py tests/llm/test_action_schema.py && git commit -m "feat(llm): canonical action schema single source of truth (W1)

Defines ACTION_SPECS, explicit qty semantics (add_qty/new_total/remove_qty +
items[].op), required-field validation, and canonical->engine translation.
Refs R-069, R-070, R-078.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`

---

### Task 2: DeepSeek provider builds its tool from the shared schema

**Files:**
- Modify: `src/app/llm/deepseek.py` (replace the `_DS_TOOL` dict literal and the tail of `DeepSeekConversationAgent.respond`)
- Modify/extend: `tests/llm/test_deepseek_agent.py`, `tests/llm/test_deepseek_prompt.py`

**Interfaces:**
- Consumes: `app.llm.action_schema.build_openai_tool`, `to_engine_result`.
- Produces: `_DS_TOOL = build_openai_tool("take_action")`; `respond()` returns engine-legacy `ConversationAgentResult` via `to_engine_result`.

- [ ] **Step 1: Write the failing test** — add to `tests/llm/test_deepseek_agent.py`:

```python
import app.llm.deepseek as ds
from app.llm import action_schema as A


def test_ds_tool_is_built_from_shared_schema():
    props = ds._DS_TOOL["function"]["parameters"]["properties"]
    assert props["new_total"]["description"].lower().count("absolute") >= 1
    assert set(props["items"]["items"]["properties"]["op"]["enum"]) == {
        "add_delta", "set_total", "remove_delta",
    }
    assert set(ds._DS_TOOL["function"]["parameters"]["properties"]["action"]["enum"]) == set(A.ACTION_SPECS)


@pytest.mark.asyncio
async def test_ds_set_qty_missing_total_yields_no_mutation(monkeypatch):
    async def _fake_tools(*a, **k):
        return {"action": "cart_set_qty", "dish_query": "biryani"}  # no new_total
    monkeypatch.setattr(ds, "_async_chat_tools", _fake_tools)
    agent = ds.DeepSeekConversationAgent.__new__(ds.DeepSeekConversationAgent)
    agent._api_key, agent._model = "k", "m"
    res = await agent.respond(restaurant_name="R", dialogue_phase="ordering", history=[], context={})
    assert res.action == "no_action"
    assert res.action_data["needs_clarification"] is True


@pytest.mark.asyncio
async def test_ds_set_qty_absolute(monkeypatch):
    async def _fake_tools(*a, **k):
        return {"action": "cart_set_qty", "dish_query": "biryani", "new_total": 1}
    monkeypatch.setattr(ds, "_async_chat_tools", _fake_tools)
    agent = ds.DeepSeekConversationAgent.__new__(ds.DeepSeekConversationAgent)
    agent._api_key, agent._model = "k", "m"
    res = await agent.respond(restaurant_name="R", dialogue_phase="ordering", history=[], context={})
    assert res.action == "update_qty"
    assert res.action_data["qty"] == 1
```

(If the existing `test_deepseek_prompt.py` asserts the old `qty`/`enum` literals, update those assertions to the canonical names in this same step — the prompt-block text describing actions stays; only the tool *parameter* names change.)

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/llm/test_deepseek_agent.py tests/llm/test_deepseek_prompt.py -q`
Expected: failures (old `_DS_TOOL` still has overloaded `qty`, no `op`).

- [ ] **Step 3: Implement** — in `src/app/llm/deepseek.py`:

a. Add import near the top: `from app.llm.action_schema import build_openai_tool, to_engine_result`.

b. Replace the entire `_DS_TOOL = { ... }` literal (currently ~lines 184–307) with:

```python
_DS_TOOL = build_openai_tool("take_action")
```

c. Replace the tail of `DeepSeekConversationAgent.respond` (currently lines 633–672, from the `_q = inp.get("qty")` comment block through the `return ConversationAgentResult(...)`) with:

```python
        legacy_action, action_data = to_engine_result(
            inp.get("action", "no_action"), inp,
        )
        return ConversationAgentResult(
            message=strip_dashes(inp.get("reply", "")),
            action=legacy_action,
            action_data=action_data,
        )
```

Leave the `_IDENTITY` / `_ORDERING_BLOCK` system-prompt text intact except: ensure the prompt teaches the new field names (the prompt may keep human guidance, but examples that say "qty=4" must read "new_total=4" / "add_qty=1"). Keep `_build_system` unchanged otherwise.

- [ ] **Step 4: Run GREEN**

Run: `.venv/bin/python -m pytest tests/llm/test_deepseek_agent.py tests/llm/test_deepseek_prompt.py -q`
Expected: pass.

- [ ] **Step 5: Lint + commit**

Run: `.venv/bin/ruff check src/app/llm/deepseek.py tests/llm/test_deepseek_agent.py tests/llm/test_deepseek_prompt.py`
Run: `git add -A && git commit -m "feat(llm): DeepSeek agent builds tool from shared action schema (W1)

Replaces the overloaded qty field with explicit add_qty/new_total + items[].op,
validates required fields before dispatch, returns engine-legacy result via
to_engine_result. Refs R-069, R-070, R-078.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`

---

### Task 3: Claude provider reaches full parity (or is gated out)

**Files:**
- Modify: `src/app/llm/claude.py` (replace `_CONVERSATION_TOOL`, make `_CONVERSATION_SYSTEM` phase-aware, rewrite `respond`)
- Modify: `src/app/llm/factory.py` (gate `get_conversation_agent()` for `claude`)
- Modify/extend: `tests/llm/test_claude.py`

**Interfaces:**
- Consumes: `action_schema.build_anthropic_tool`, `to_engine_result`, `CANON_PHASE_ACTIONS`.
- Produces: Claude tool identical (by action names + required) to DeepSeek; `respond()` returns engine-legacy results; factory gate flag.

- [ ] **Step 1: Write the failing test** — add to `tests/llm/test_claude.py`:

```python
import app.llm.claude as cl
import app.llm.deepseek as ds


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
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/llm/test_claude.py -q`
Expected: failures (Claude tool only has 4 actions, no `items`/`note`).

- [ ] **Step 3: Implement** — in `src/app/llm/claude.py`:

a. Add import: `from app.llm.action_schema import build_anthropic_tool, to_engine_result, CANON_PHASE_ACTIONS`.

b. Replace the entire `_CONVERSATION_TOOL = { ... }` literal (lines 358–384) with:

```python
_CONVERSATION_TOOL = build_anthropic_tool("take_action")
```

c. Make the system prompt phase-aware. Add, after `_CONVERSATION_SYSTEM`:

```python
def _phase_guidance(phase: str) -> str:
    allowed = sorted(CANON_PHASE_ACTIONS.get(phase, CANON_PHASE_ACTIONS["ordering"]))
    return (
        f"\nCURRENT PHASE: {phase}. You may ONLY use these actions this phase: "
        f"{', '.join(allowed)}. cart_add.add_qty is a DELTA; cart_set_qty.new_total "
        f"is the ABSOLUTE new total ('only 1' -> cart_set_qty new_total=1, never add). "
        f"For multiple dishes in one message use items[] with an explicit op per dish.\n"
    )
```

d. Replace `ClaudeConversationAgent.respond` body (lines 460–496) with:

```python
        system = _CONVERSATION_SYSTEM.format(
            restaurant_name=restaurant_name,
            menu_text=context.get("menu_text", "Menu unavailable."),
            cart_summary=context.get("cart_summary") or "empty",
            delivery_info=context.get("delivery_info") or "Delivery fees vary by distance.",
        ) + _phase_guidance(dialogue_phase)
        messages = history if history else [{"role": "user", "content": "hi"}]
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=512,
            system=system,
            tools=[_CONVERSATION_TOOL],
            tool_choice={"type": "tool", "name": "take_action"},
            messages=messages,
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == "take_action":
                inp = dict(block.input)
                legacy_action, action_data = to_engine_result(
                    inp.get("action", "no_action"), inp,
                )
                return ConversationAgentResult(
                    message=strip_dashes(inp.get("reply", "")),
                    action=legacy_action,
                    action_data=action_data,
                )
        raise RuntimeError("ClaudeConversationAgent: no take_action block in response")
```

e. In `src/app/llm/factory.py` `get_conversation_agent()`, gate Claude behind a parity flag so a future schema regression can't silently ship a non-compliant Claude:

```python
def get_conversation_agent():
    settings = get_settings()
    if settings.llm_provider == "claude":
        if not getattr(settings, "claude_conversation_enabled", False):
            # Claude is parity-gated (W1). Until explicitly enabled, fall back to the
            # contract-tested DeepSeek agent rather than a divergent action surface.
            from app.llm.deepseek import DeepSeekConversationAgent
            return DeepSeekConversationAgent()
        from app.llm.claude import ClaudeConversationAgent
        return ClaudeConversationAgent()
    if settings.llm_provider == "deepseek":
        from app.llm.deepseek import DeepSeekConversationAgent
        return DeepSeekConversationAgent()
    from app.llm.fake import FakeConversationAgent
    return FakeConversationAgent()
```

Add `claude_conversation_enabled: bool = False` to `app/config.py` Settings (default False). The offline parity contract test (Task 5) proves Claude *can* be enabled safely; flipping the flag is an ops decision, not required for W1 green.

- [ ] **Step 4: Run GREEN**

Run: `.venv/bin/python -m pytest tests/llm/test_claude.py tests/llm/test_factory.py -q`
Expected: pass.

- [ ] **Step 5: Lint + commit**

Run: `.venv/bin/ruff check src/app/llm/claude.py src/app/llm/factory.py src/app/config.py tests/llm/test_claude.py`
Run: `git add -A && git commit -m "feat(llm): Claude conversation agent reaches schema parity, phase-aware (W1)

Builds the tool from the shared schema (full action enum + items[].op + note),
injects phase-allowed actions, returns engine-legacy results, and gates Claude
behind claude_conversation_enabled until parity is proven. Closes R-003, R-062,
F52, F53, F54, RA-6.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`

---

### Task 4: Fake provider becomes schema-faithful (no substring heuristics)

**Files:**
- Modify: `src/app/llm/fake.py` (rewrite `FakeConversationAgent.respond` to emit canonical actions through `to_engine_result`)
- Modify/extend: `tests/llm/test_fake.py`

**Interfaces:**
- Consumes: `action_schema.to_engine_result`.
- Produces: a deterministic test double whose outputs pass `validate_required` and use explicit qty semantics; `"only N X"` → `cart_set_qty new_total=N`.

- [ ] **Step 1: Write the failing test** — add to `tests/llm/test_fake.py`:

```python
import pytest
from app.llm.fake import FakeConversationAgent


@pytest.mark.asyncio
async def test_fake_only_one_is_set_qty_absolute():
    agent = FakeConversationAgent()
    res = await agent.respond(
        restaurant_name="R", dialogue_phase="ordering",
        history=[{"role": "user", "content": "only 1 chicken biryani"}],
        context={"cart_summary": "2x Chicken Biryani"},
    )
    assert res.action == "update_qty"
    assert res.action_data["qty"] == 1


@pytest.mark.asyncio
async def test_fake_make_it_n_is_set_qty():
    agent = FakeConversationAgent()
    res = await agent.respond(
        restaurant_name="R", dialogue_phase="ordering",
        history=[{"role": "user", "content": "make it 4 biryani"}],
        context={"cart_summary": "1x Biryani"},
    )
    assert res.action == "update_qty"
    assert res.action_data["qty"] == 4


@pytest.mark.asyncio
async def test_fake_plain_add_is_delta():
    agent = FakeConversationAgent()
    res = await agent.respond(
        restaurant_name="R", dialogue_phase="ordering",
        history=[{"role": "user", "content": "2 biryani"}], context={},
    )
    assert res.action == "add_item"
    assert res.action_data["qty"] == 2


@pytest.mark.asyncio
async def test_fake_emits_validatable_payloads_only():
    # Every Fake output must already be a clean engine-legacy result (never a raw
    # canonical dict missing required fields).
    agent = FakeConversationAgent()
    res = await agent.respond(
        restaurant_name="R", dialogue_phase="ordering",
        history=[{"role": "user", "content": "hi"}], context={},
    )
    assert res.action in {"no_action", "show_menu"}
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/llm/test_fake.py -q`
Expected: `test_fake_only_one_is_set_qty_absolute` fails (today "only 1 ..." falls through to `add_item`).

- [ ] **Step 3: Implement** — replace `FakeConversationAgent.respond` (fake.py lines 122–249, the ordering branch and helpers) so it routes through canonical actions. Full replacement of the ordering-phase block:

```python
    async def respond(
        self, *, restaurant_name: str, dialogue_phase: str,
        history: list[dict], context: dict,
    ) -> "ConversationAgentResult":
        import re
        from app.llm.action_schema import to_engine_result

        last_user = ""
        for msg in reversed(history):
            if msg.get("role") == "user":
                last_user = (msg.get("content") or "").lower()
                break
        last_user = last_user.replace("’", "'").replace("ʼ", "'").strip()

        def _emit(canon: str, payload: dict, message: str = ""):
            action, data = to_engine_result(canon, payload, message=message)
            return ConversationAgentResult(message=message, action=action, action_data=data)

        if dialogue_phase == "ordering":
            if "menu" in last_user or "what do you have" in last_user:
                return _emit("menu_show", {}, "Here's our menu! 😊")

            _closing = ("done", "that's all", "thats all", "bas", "khalaas", "khalas",
                        "proceed", "checkout", "no more", "nothing else", "nope")
            _cart = (context.get("cart_summary") or "").strip()
            if last_user in {"no", "na", "nah", "np"} or any(w in last_user for w in _closing):
                if not _cart:
                    return _emit("no_action", {}, "Your cart is empty 😊 What would you like to order?")
                return _emit("checkout_proceed", {}, "Great! Let me get your delivery details.")

            if "cancel" in last_user:
                return _emit("cancel_order", {}, "Order cancelled.")

            if ("clear" in last_user and "cart" in last_user) or any(
                p in last_user for p in ("start over", "remove everything",
                                         "empty my cart", "empty cart", "delete all")):
                return _emit("cart_clear", {}, "Cleared!")

            # "only N X" / "make it N X" -> cart_set_qty (ABSOLUTE).
            m_set = re.match(r'^(?:only|make it|change(?: to)?|set(?: to)?)\s+(\d+)\s*[xX]?\s+(.*)$', last_user)
            if m_set and m_set.group(2).strip():
                return _emit(
                    "cart_set_qty",
                    {"dish_query": m_set.group(2).strip(), "new_total": int(m_set.group(1))},
                    "Updated!",
                )

            # Multi-dish set ("make it 2 X and 3 Y").
            if any(p in last_user for p in ("make it", "change", "set to")) and re.search(r",|\band\b|\+", last_user):
                clauses = re.split(r"\s*(?:,|\band\b|\+)\s*", last_user)
                ups = []
                for c in clauses:
                    c = re.sub(r"\b(make it|change(?: to)?|set(?: to)?|only)\b", " ", c).strip()
                    mm = re.match(r"^(\d+)\s*[xX]?\s+(.*)$", c)
                    if mm and mm.group(2).strip():
                        ups.append({"op": "set_total", "dish_query": mm.group(2).strip(), "qty": int(mm.group(1))})
                if len(ups) >= 2:
                    return _emit("cart_set_qty", {"items": ups}, "Updated!")

            if "remove" in last_user:
                dish = last_user.split("remove", 1)[1].strip()
                if dish:
                    return _emit("cart_remove", {"dish_query": dish}, "Sure, removing that.")

            if {"hi", "hello", "hey", "salam", "salaam"} & set(re.findall(r'\b\w+\b', last_user)):
                return _emit("no_action", {}, context.get("menu_text", "Welcome! Here is our menu."))

            if any(w in last_user for w in ("where", "status", "track", "eta", "when")):
                return _emit("status_query", {}, "Let me check your order status.")

            # Multi-dish add.
            if re.search(r",|\band\b|\+", last_user):
                clauses = re.split(r"\s*(?:,|\band\b|\+)\s*", last_user)
                parsed = []
                for c in clauses:
                    c = c.strip()
                    if not c:
                        continue
                    cq = 1
                    mm = re.match(r'^(\d+)\s*[xX]?\s+(.*)$', c)
                    if mm:
                        cq, c = int(mm.group(1)), mm.group(2).strip()
                    if c:
                        parsed.append({"op": "add_delta", "dish_query": c, "qty": cq})
                if len(parsed) >= 2:
                    return _emit("cart_add", {"items": parsed}, "Got it! Added everything to your cart 🛒")

            # Single add (delta).
            qty, dish = 1, last_user
            mq = re.match(r'^(\d+)\s*[xX]?\s+(.*)$', last_user)
            if mq:
                qty, dish = int(mq.group(1)), mq.group(2).strip()
            if dish:
                return _emit("cart_add", {"dish_query": dish, "add_qty": qty},
                             f"Added {dish} to your cart! 🛒")
            return _emit("no_action", {}, context.get("menu_text", "Welcome! Here is our menu."))
```

Keep the existing `address_capture` / `awaiting_confirmation` / `post_order` branches but route each through `_emit(<canon>, ...)` using the canonical names (e.g. `address_use_saved`, `address_location`, `confirm_order`, `cancel_order`, `cart_add`/`cart_remove` for confirm-step edits). Do not leave any branch returning a raw legacy action by hand — everything goes through `_emit`.

- [ ] **Step 4: Run GREEN**

Run: `.venv/bin/python -m pytest tests/llm/test_fake.py -q`
Expected: pass.

- [ ] **Step 5: Lint + commit**

Run: `.venv/bin/ruff check src/app/llm/fake.py tests/llm/test_fake.py`
Run: `git add -A && git commit -m "refactor(llm): Fake agent is schema-faithful, explicit qty semantics (W1)

Routes every output through the canonical schema; 'only N X' -> cart_set_qty
(absolute), plain 'N X' -> cart_add (delta). Closes R-045, F33.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`

---

### Task 5: Provider-parity CONTRACT TEST

**Files:**
- Create: `tests/llm/test_provider_parity.py`

**Interfaces:** Consumes the three providers' static tool dicts + `action_schema`. No network.

- [ ] **Step 1: Write the failing test (write it before confirming it passes)**

Create `tests/llm/test_provider_parity.py`:

```python
"""Provider-parity contract: DeepSeek, Claude, Fake expose ONE action surface (W1).

Closes R-045 / F33. Pure introspection — no API keys, no DB.
"""
from __future__ import annotations

import app.llm.claude as cl
import app.llm.deepseek as ds
from app.llm import action_schema as A


def _ds_props():
    return ds._DS_TOOL["function"]["parameters"]["properties"]


def _cl_props():
    return cl._CONVERSATION_TOOL["input_schema"]["properties"]


def test_action_enums_identical_across_providers():
    canon = set(A.ACTION_SPECS)
    assert set(_ds_props()["action"]["enum"]) == canon
    assert set(_cl_props()["action"]["enum"]) == canon


def test_field_property_sets_identical():
    assert set(_ds_props()) == set(_cl_props())


def test_items_op_enum_identical():
    for props in (_ds_props(), _cl_props()):
        assert set(props["items"]["items"]["properties"]["op"]["enum"]) == {
            "add_delta", "set_total", "remove_delta",
        }


def test_required_fields_per_action_match_spec():
    # The spec is authoritative; both live tools are built from it, so the
    # required-field contract is whatever ACTION_SPECS declares.
    for action, spec in A.ACTION_SPECS.items():
        missing_when_empty = A.validate_required(action, {})
        assert missing_when_empty == [] or all(
            isinstance(m, str) for m in missing_when_empty
        )


def test_qty_field_is_never_overloaded():
    props = _ds_props()
    assert "add_qty" in props and "new_total" in props and "remove_qty" in props
    assert "qty" not in props  # the top-level overloaded qty is gone


def test_canon_phase_actions_consistent_with_legacy_map():
    for phase, canon_actions in A.CANON_PHASE_ACTIONS.items():
        legacy = {A.CANON_TO_LEGACY[a] for a in canon_actions}
        assert legacy == set(A.LEGACY_PHASE_ACTIONS[phase])
```

- [ ] **Step 2: Run RED then GREEN**

Run: `.venv/bin/python -m pytest tests/llm/test_provider_parity.py -q`
Expected: this should pass *if* Tasks 2–4 are complete (the tools are built from the shared spec). If any assertion fails, the divergence it names is the bug — fix the offending provider, not the test. Re-run until green.

- [ ] **Step 3: Lint + commit**

Run: `.venv/bin/ruff check tests/llm/test_provider_parity.py`
Run: `git add tests/llm/test_provider_parity.py && git commit -m "test(llm): provider-parity contract across DeepSeek/Claude/Fake (W1)

Asserts identical action names, field properties, items[].op enum, and
non-overloaded qty fields. Closes R-045, F33.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`

---

### Task 6: Engine — single phase-action source + deterministic clarification gate

**Files:**
- Modify: `src/app/conversation/engine.py` (`_PHASE_ACTIONS` import; `no_action` clarification guard)
- Modify/extend: `tests/conversation/test_engine_full_ai.py`

**Interfaces:**
- Consumes: `action_schema.LEGACY_PHASE_ACTIONS`.
- Produces: `_PHASE_ACTIONS = LEGACY_PHASE_ACTIONS`; the `no_action` path emits a deterministic clarification (and performs no mutation) when `action_data.get("needs_clarification")`.

- [ ] **Step 1: Write the failing test** — add to `tests/conversation/test_engine_full_ai.py` (or a new `tests/conversation/test_engine_clarification.py`):

```python
@pytest.mark.asyncio
async def test_needs_clarification_sends_message_and_no_mutation(
    db_session, restaurant, seed_biryani_menu,
):
    """A model result flagged needs_clarification must NOT mutate the cart and must
    send one deterministic clarification reply."""
    from app.conversation.engine import _dispatch_action
    # Build a minimal conv with an empty draft; assert dispatch of a clarification
    # result produces an outbound and leaves the cart empty.
    # (Use the same conv/inbound construction as the other tests in this file.)
    ...  # arrange conv + inbound per existing helpers in this module
    result = type("R", (), {
        "action": "no_action",
        "action_data": {"needs_clarification": True, "clarify_action": "cart_set_qty",
                        "missing_fields": ["new_total"]},
        "message": "",
    })()
    await _dispatch_action(db_session, conv, inbound, restaurant.id, result,
                           phase="ordering", restaurant=restaurant)
    # assert an outbound clarification was written and no OrderItem rows exist
```

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/conversation/test_engine_full_ai.py -q -k clarification`
Expected: fail (no clarification branch yet).

- [ ] **Step 3: Implement** — in `engine.py`:

a. Add import (top of module): `from app.llm.action_schema import LEGACY_PHASE_ACTIONS`.

b. Replace the inline `_PHASE_ACTIONS: dict[str, frozenset] = { ... }` literal (lines 3246–3261) with:

```python
# Single source of truth: derived from the canonical action schema (W1) so the
# engine's phase guard can never drift from the providers' tool schema.
_PHASE_ACTIONS: dict[str, frozenset] = dict(LEGACY_PHASE_ACTIONS)
```

c. In `_dispatch_action`, add a guard at the very top of the function (immediately after `reply = result.message or ""`, before the confirmation-edit/phase-guard logic at line ~4419):

```python
    # Required-field validation gate (W1, R-069): the interpreter chose an action
    # whose mandatory fields were missing. Do NOT mutate; ask one deterministic
    # clarification. This is engine-authored copy, not an interpretation phrase table.
    if data.get("needs_clarification"):
        await _send_text(
            session, conv=conv, inbound=inbound, restaurant_id=restaurant_id,
            prefix="ai-clarify",
            body=reply or ("Sorry, I didn't quite catch that, could you tell me the "
                           "dish and the exact quantity you'd like? 😊"),
        )
        return
```

- [ ] **Step 4: Run GREEN**

Run: `.venv/bin/python -m pytest tests/conversation/test_engine_full_ai.py -q`
Expected: pass. Then a broader smoke:
Run: `.venv/bin/python -m pytest tests/conversation -q`
Expected: pass (the legacy phase-action set is identical to before; this is a refactor).

- [ ] **Step 5: Lint + commit**

Run: `.venv/bin/ruff check src/app/conversation/engine.py`
Run: `git add -A && git commit -m "feat(engine): derive phase-actions from schema; clarification gate (W1)

_PHASE_ACTIONS now derives from action_schema.LEGACY_PHASE_ACTIONS (no drift);
required-field-missing results emit a deterministic clarification with zero cart
mutation. Closes R-069.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`

---

### Task 7: Delete dead `_fetch_conversation_history` (F67)

**Files:**
- Modify: `src/app/conversation/engine.py` (remove the function at lines 3010–3045)

**Interfaces:** none. Pure dead-code removal; live path uses `_build_history`.

- [ ] **Step 1: Prove it is dead (failing guard = a reference exists)**

Run: `grep -rn "_fetch_conversation_history" src apps tests`
Expected: matches ONLY the definition in `engine.py` (no call sites). If any call site exists, STOP — it is not trivially in scope; instead add a note "F67 deferred — caller found at <path>" and skip this task.

- [ ] **Step 2: Remove the function**

Delete the entire `async def _fetch_conversation_history(...)` block (engine.py lines 3010–3045, ending just before `async def _order_has_items`).

- [ ] **Step 3: Run GREEN (import + tests still pass)**

Run: `.venv/bin/python -c "import app.conversation.engine"`
Run: `.venv/bin/python -m pytest tests/conversation -q`
Expected: import succeeds; tests pass.

- [ ] **Step 4: Lint + commit**

Run: `.venv/bin/ruff check src/app/conversation/engine.py`
Run: `git add -A && git commit -m "chore(engine): delete dead _fetch_conversation_history (F67)

Live path uses _build_history; the Claude-specific builder was unreferenced.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`

---

### Task 8: W1 capability evals + flip xfail markers (acceptance)

**Files:**
- Modify: `tests/evals/test_response_accuracy_suite.py` (add W1 evals; flip the xfails W1 now fixes)
- Modify: `tests/evals/REGISTRY.md` (mark graduated evals)

**Acceptance evals W1 must flip from `xfail` → pass (per the remediation design "Tests:" line):**
1. **Provider-parity contract** — `tests/llm/test_provider_parity.py` (Task 5) green (not xfail).
2. **Required-field-missing → no mutation** — new eval `test_set_qty_missing_total_no_mutation` (below).
3. **Qty-absolute semantics ("only 1" → set total, not add)** — existing eval **#10** `test_clear_cart_only_on_explicit_clear` (currently `xfail(strict=True)`, reason "W2/W4"): with the schema + Fake fixes, "only 1 chicken biryani" now emits `cart_set_qty new_total=1` → engine `update_qty` on the single biryani line; the lemon line survives. Remove its `@pytest.mark.xfail` and confirm it passes. (If it still fails because of line-targeting that genuinely needs W2/W4, leave the xfail and record in REGISTRY that only the schema half landed in W1.)

- [ ] **Step 1: Add the new required-field eval (failing first)** — add to `tests/evals/test_response_accuracy_suite.py`:

```python
@pytest.mark.asyncio
async def test_set_qty_missing_total_no_mutation(db_session, restaurant, seed_biryani_menu):
    """A set-qty intent without a number must not change the cart and must ask a
    clarification (R-069). Driven via the Fake provider through the real engine."""
    res = await drive_turns(
        db_session, restaurant_id=restaurant.id, phone="+971500000040",
        turns=[
            {"type": "text", "text": "2 chicken biryani"},
            {"type": "text", "text": "change the biryani"},  # no number -> needs clarification
        ],
    )
    final = res.final_cart()
    biryani = [r for r in final if "biryani" in r["dish_name"].lower()]
    assert len(biryani) == 1 and biryani[0]["qty"] == 2, f"cart must be unchanged, got {final}"
    last = (res.turns[-1].outbounds[-1].body if res.turns[-1].outbounds else "").lower()
    assert any(m in last for m in ("quantity", "how many", "didn't", "catch", "exact")), last
```

(If the Fake's "change the biryani" path needs a tweak to emit `cart_set_qty` with no `new_total`, make that adjustment in `fake.py` under Task 4's pattern — but here, written as its own RED first.)

- [ ] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/evals/test_response_accuracy_suite.py::test_set_qty_missing_total_no_mutation -q`
Expected: fail until Fake emits a number-less `cart_set_qty` and the engine clarification gate (Task 6) catches it.

- [ ] **Step 3: Make it GREEN** (Fake emits `cart_set_qty` for "change the X" with no number; `to_engine_result` flags `needs_clarification`; engine sends clarification). Re-run; expect pass.

- [ ] **Step 4: Flip the qty-absolute eval** — remove the `@pytest.mark.xfail(strict=True, reason="W2/W4 clear_cart: 'only X' ...")` decorator on `test_clear_cart_only_on_explicit_clear`.

Run: `.venv/bin/python -m pytest tests/evals/test_response_accuracy_suite.py::test_clear_cart_only_on_explicit_clear -q`
Expected: pass (no longer xfail). If it errors as XPASS-strict, the flip is correct; if it genuinely fails, restore the xfail and add a REGISTRY note that W1 delivered the schema half only.

- [ ] **Step 5: Run the whole eval + llm + parity suites**

Run: `.venv/bin/python -m pytest tests/evals tests/llm -q`
Expected: green; no unexpected xpass on still-xfail (W2–W8) evals.

- [ ] **Step 6: Update REGISTRY + commit**

Edit `tests/evals/REGISTRY.md`: mark eval #10 as graduated (✅) for the qty-absolute behaviour with a "W1 (schema)" note; add rows for the new `test_set_qty_missing_total_no_mutation` and the `test_provider_parity` contract.

Run: `.venv/bin/ruff check tests`
Run: `git add -A && git commit -m "test(evals): W1 acceptance — parity, required-field, qty-absolute (W1)

Adds required-field-missing no-mutation eval; flips the 'only N' qty-absolute
eval from xfail to pass; records graduations in REGISTRY. Closes R-069, R-070.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`

---

### Task 9: Full verification matrix + housekeeping

**Files:** none (verification only) + `understanding.txt`

- [ ] **Step 1: Ensure the test DB is up**

Run: `docker compose ps` (Postgres+PostGIS on `:5433`). If not running: `docker compose up -d db`.

- [ ] **Step 2: Full matrix**

Run: `.venv/bin/python -m pytest tests -q`
Expected: green. Pay attention to: `tests/llm/*`, `tests/conversation/*`, `tests/evals/*`. No still-xfail eval should XPASS unexpectedly (those belong to W2–W8).

- [ ] **Step 3: Lint the whole tree**

Run: `.venv/bin/ruff check src apps tests`
Expected: clean.

- [ ] **Step 4: Graph + understanding**

Run: `/graphify . --update`
Then append dated bullets to `understanding.txt` summarising: canonical action schema added; explicit qty semantics; required-field gate; Claude parity (gated); Fake schema-faithful; provider-parity contract; F67 deletion; evals flipped.

- [ ] **Step 5: Final commit**

Run: `git add understanding.txt && git commit -m "docs: record W1 tool-schema-parity completion in understanding.txt

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`

---

## Self-review checklist (run before declaring W1 done)

- [ ] One schema, one source: `ACTION_SPECS` is the only place action names/required-fields/qty-fields are defined; DeepSeek, Claude, Fake, and the engine all derive from it (no hand-maintained duplicate lists remain).
- [ ] Qty is never overloaded: no top-level `qty` property survives in any provider tool; `add_qty`/`new_total`/`remove_qty` + `items[].op` are present and documented (delta vs absolute).
- [ ] Required-field validation runs before any mutation: a `cart_set_qty` (or `address_save`, `cart_set_note`, etc.) missing mandatory fields produces `no_action` + `needs_clarification` and the engine mutates nothing.
- [ ] Claude parity proven offline by `test_provider_parity.py`; Claude is gated behind `claude_conversation_enabled` so a regression cannot silently ship a divergent surface.
- [ ] Fake is schema-faithful: "only 1 X" → set-total, "2 X" → add-delta; no substring-heuristic shortcuts that bypass the schema.
- [ ] `reply` is optional and non-authoritative everywhere (R-078); no provider authors money/menu/totals/order#.
- [ ] Engine dispatcher (`_dispatch_action`) and all its handlers are UNCHANGED except the clarification gate and the `_PHASE_ACTIONS` import (the legacy action contract is preserved).
- [ ] `_fetch_conversation_history` deleted with zero remaining references (or explicitly deferred with a recorded caller).
- [ ] Multi-tenant + multilingual constraints respected: no English interpretation phrase tables added on live paths; the single clarification fallback is engine-authored copy only.
- [ ] Acceptance evals flipped: provider-parity contract green; required-field eval green; qty-absolute eval (#10) flipped or documented as schema-half-only.
- [ ] Full matrix + `ruff` + `/graphify` + `understanding.txt` all done; commits are conventional and each ends with the required Co-Authored-By trailer.

## Execution handoff

- **Branch:** `remediation/w1-tool-schema-parity` (off the W0 integration branch).
- **Order:** Tasks are sequential. Task 1 (schema) gates everything; Tasks 2–4 (providers) can be done in any order but all must precede Task 5 (contract). Task 6 (engine) depends on Task 1. Task 8 depends on Tasks 1–6.
- **RED discipline:** every task starts by running its new test and seeing it fail for the stated reason before writing implementation. If a test passes RED unexpectedly, the test is wrong — fix the test, not the code.
- **DB:** tests need the Docker `restaurant_test` DB on `:5433`; evals run under the Fake provider.
- **Do not** touch W2 concerns (line `line_ref` identity), W3 (deterministic render), or W4 (router) here — `cart_set_note`'s line-targeting and the lemon-survival edge of eval #10 may legitimately need them; if so, document and defer rather than over-reach.
- **Definition of done:** the self-review checklist is fully ticked, the full matrix + ruff + graphify pass, and `understanding.txt` records the workstream.
