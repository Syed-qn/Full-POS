# W1 Task 8 — Eval Graduation Report

**Branch:** `worktree-task8-w1-evals` (based on `remediation/w0-eval-harness` @ b9ae270)
**Date:** 2026-07-01

---

## 1. Baseline (before T8)

Ran `pytest tests/evals tests/llm tests/conversation` from the worktree:

- **295 passed, 11 xfailed, 0 unexpected xpass, 0 failures**

All 11 xfailed evals are genuine capability gaps whose fixes belong to W2–W8.
No W1-tagged eval was ready to graduate.

---

## 2. What W1 acceptance criteria required

| Criterion | Status |
|-----------|--------|
| Provider-parity (Fake/DeepSeek/Claude behave identically on shared contract) | Already green in T1–T7 LLM tests (92 pass) — no new eval needed |
| R-069: required-field-missing → clarification, NO cart mutation | No eval existed → must add |
| Qty-absolute semantics ("only 1 X" → `cart_set_qty`, not delta) | Eval #10 — still xfail (W2+W4 routing fix needed) |

---

## 3. Eval graduation decisions

### Eval #10 (`test_clear_cart_only_on_explicit_clear`) — xfail RETAINED

Root cause investigation:

1. The W1 schema layer is correct: `cart_set_qty` with `requires_one_of` is wired.
2. `FakeConversationAgent` correctly emits `cart_set_qty(dish_query, new_total=1)` for "only 1 chicken biryani".
3. However, `_try_catalog_typed_order()` in `engine.py` intercepts "only 1 chicken biryani" **before** the AI runs (catalog mode is enabled by the `seed_biryani_menu` fixture via `catalog_ordering_enabled=True`), treats it as a delta add of qty=1, and increments the existing cart (2 → 3 instead of setting to 1).

This is a W2+W4 routing fix (teach `_try_catalog_typed_order` to recognise "only N X" as a set-absolute intent). Removing the xfail without that fix would be dishonest. xfail retained with a REGISTRY note.

### Eval #21 (`test_set_qty_missing_total_no_mutation`) — NEW regression eval

Added to cover R-069. Flow verified end-to-end:

1. Turn 1: "2 chicken biryani" → cart {biryani: qty=2}
2. Turn 2: "change the biryani" (no number) → `FakeConversationAgent` `m_no_qty` branch emits `cart_set_qty({dish_query: "biryani"})` without `new_total`
3. `to_engine_result()` → `validate_required` finds `requires_one_of` group 2 (`new_total`, `items`) unsatisfied → returns `("no_action", {needs_clarification: True, missing_fields: ["new_total"]})`
4. Engine clarification gate (`if data.get("needs_clarification"):`) fires → sends clarification reply, exits without calling `_execute_ai_update_qty`
5. Cart remains {biryani: qty=2}; reply contains "quantity"/"how many" keyword

Test passes (confirmed).

---

## 4. Code changes

### `src/app/llm/fake.py`

Added `m_no_qty` branch in `FakeConversationAgent.respond()`, between the `m_set` block (which handles "change N X" with a number) and the `remove` check:

```python
m_no_qty = re.match(
    r"^(?:change|update|modify)\s+(?:the\s+|my\s+)?(.+)$",
    last_user,
)
if m_no_qty and m_no_qty.group(1).strip():
    return _emit("cart_set_qty", {"dish_query": m_no_qty.group(1).strip()}, "")
```

This intentionally omits `new_total`. `to_engine_result` converts this incomplete action into `no_action + needs_clarification=True`.

### `tests/evals/test_response_accuracy_suite.py`

Added `test_set_qty_missing_total_no_mutation` (no xfail marker — immediate regression).

### `pyproject.toml`

Added `pythonpath = ["src"]` under `[tool.pytest.ini_options]`.

**Why:** The `.venv` is an editable install from the parent workspace (`pip install -e .` from parent `src/`). Without `pythonpath`, pytest running from the worktree imported `app.llm.fake` from the parent's `src/`, not the worktree's. Adding `pythonpath = ["src"]` prepends the worktree's `src/` to `sys.path`, ensuring worktree modules shadow the editable install.

### `tests/evals/REGISTRY.md`

- Added eval #21 row.
- Updated summary table (21 logical evals, 22 test functions).
- Added note explaining eval #10 W1 schema status vs W2+W4 routing fix.

---

## 5. Final suite result

```
296 passed, 11 xfailed, 0 warnings (relevant), 0 failures, 0 unexpected xpass
```

Ruff: all checks passed on changed files.

---

## 6. What W2/W3/W4 must do for eval #10

`_try_catalog_typed_order` needs to recognise the `only N X` / `make it N X` pattern as an explicit absolute-set intent and skip its delta-add path (or route to `set_item_qty` directly). That change is a W2/W4 concern and must not be attempted here.
