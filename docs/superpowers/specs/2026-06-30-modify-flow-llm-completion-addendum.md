# Addendum: LLM-driven completion in the order-modification flow

**Date:** 2026-06-30
**Parent spec:** 2026-06-30-consistent-multilingual-order-completion-design.md
**Status:** Approved (user chose "Route to LLM (consistent)")

## Problem

`_handle_modify_items` (engine.py:2131, live — dispatched at engine.py:5227) finalizes a
proposed order modification when the customer signals "done". It uses a hardcoded
English-only gate:

```python
if lower_q in ("done", "checkout", "that's all", "thats all"):
```

This is the same brittle pattern the parent fix removed from the main ordering flow.
A non-English or curly-apostrophe completion ("khalas", "bas", "that's all" with
U+2019) is parsed as a dish name → NO_MATCH → "we don't have khalas", instead of
finalizing the modification. Violates the multilingual / no-hardcoding requirement.

## Design

Introduce a dedicated LLM completion-intent detector, mirroring the existing
`IntentClassifierPort` provider pattern, and route the modify-flow completion check
through it.

### New port — `app/llm/port.py`
```python
class CompletionDetectorPort(Protocol):
    async def is_completion(self, text: str) -> bool:
        """True if the message means the customer is finished / wants to proceed,
        in ANY language. NOT a completion if they name a dish or ask a question."""
        ...
```

### Provider impls
- `DeepSeekCompletionDetector` (deepseek.py): one tiny async chat call (max_tokens≈4)
  asking yes/no whether the message means "finished, in any language". Returns
  `False` for empty text.
- `ClaudeCompletionDetector` (claude.py): parity impl following `ClaudeIntentClassifier`.
- `FakeCompletionDetector` (fake.py): deterministic test double — normalizes curly
  apostrophes and matches a multilingual closing-token set (incl. bas/khalas/Hindi),
  same spirit as `FakeConversationAgent`'s closing logic. Test-double only.

### Factory — `app/llm/factory.py`
`get_completion_detector()` dispatches by `settings.llm_provider` (claude / deepseek /
fake), identical shape to `get_intent_classifier()`.

### Wiring — `_handle_modify_items`
Replace the hardcoded list with:
```python
from app.llm.factory import get_completion_detector
if await get_completion_detector().is_completion(text):
    ... existing finalize branch ...
```
Detector receives the RAW `text` (not parsed `dish_query`). All other modify-flow
behavior (proposed-item accumulation, "what is", dish matching) is unchanged.

## Out of scope
- The DEAD `_handle_collecting_items` / `_is_checkout_intent` path (no live caller) is
  left untouched — it is pre-existing dead code, not on any live path.
- Main ordering flow (already LLM-driven via the parent fix).

## Tests
- `FakeCompletionDetector` unit tests: English, curly apostrophe, bas/khalas, a dish
  name → False, a question → False.
- Modify-flow integration test: a customer mid-modification sends a non-English /
  curly completion → modification is finalized (dialogue_state → modify_confirm),
  not treated as an unknown dish.

## Success criteria
- No hardcoded English completion table on any LIVE path.
- Modify completion works in any language / apostrophe style.
- All existing modify tests still pass.
