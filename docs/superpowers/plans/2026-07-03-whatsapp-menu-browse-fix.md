# WhatsApp Menu Browse & Suggestion Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix empty menu/suggestion WhatsApp replies (catalogue + text tenants), stop compaction JSON leaks, align prompts in `context.txt`, and add a grounded suggestion sub-agent for open-ended recommend requests.

**Architecture:** Deterministic engine guards (browse intents, dish search, menu-promise fulfillment, compaction sanitization) run before the lead LLM; a focused suggestion sub-agent picks ≤3 validated dishes when the candidate set is large or the request is vague; prompts in `context.txt` / `conversation_prompts.py` align model behaviour with engine delivery.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async, pytest, existing LLM providers (Fake/DeepSeek/Claude), WhatsApp catalogue via `send_catalog()`.

**Spec:** `docs/superpowers/specs/2026-07-03-whatsapp-menu-browse-fix-design.md`

---

## File map

| File | Responsibility |
|------|----------------|
| `src/app/conversation/engine.py` | Intent detectors, browse handlers, phase reset, history/sanitizer, dispatch guards |
| `src/app/llm/action_schema.py` | `menu_show` allowed in `post_order` |
| `src/app/llm/suggestion_agent.py` | New sub-agent (system prompt, parsers, DeepSeek/Claude) |
| `src/app/llm/port.py` | `SuggestionAgentPort` protocol |
| `src/app/llm/factory.py` | `get_suggestion_agent()` |
| `src/app/llm/fake.py` | `FakeSuggestionAgent` for tests |
| `context.txt` | Goldmine prompt rules (browse/suggest/never JSON) |
| `src/app/llm/conversation_prompts.py` | Runtime prompt mirror |
| `tests/conversation/test_menu_browse.py` | Browse + post_order + catalogue/text |
| `tests/conversation/test_dish_search.py` | Ingredient filter + state |
| `tests/conversation/test_compaction_leak.py` | History role + sanitizer |
| `tests/llm/test_suggestion_agent.py` | Sub-agent parse + validation |

---

### Task 1: Compaction history + outbound sanitizer

**Files:**
- Create: `tests/conversation/test_compaction_leak.py`
- Modify: `src/app/conversation/engine.py` (`_render_history_content`, `_build_history`, `_send_text`)

- [ ] **Step 1: Write failing tests**

```python
# tests/conversation/test_compaction_leak.py
import json
import pytest
from app.conversation.engine import _build_history, _is_internal_leak, _render_history_content
from app.conversation.compaction import build_compact_summary
from app.conversation.models import Message
from app.conversation.service import record_message


def test_render_system_summary_uses_summary_field():
    msg = Message(
        conversation_id=1, direction="outbound", type="system_summary",
        payload={"summary": "[Earlier conversation summary]\nOrder ref: 1", "compacted_count": 5},
    )
    assert "Order ref: 1" in _render_history_content(msg)


@pytest.mark.asyncio
async def test_build_history_puts_system_summary_as_system_role(db_session, restaurant):
    # seed conv + system_summary row; assert history contains role=system, not assistant echo
    ...


def test_is_internal_leak_detects_compaction_json():
    body = json.dumps({"summary": "[Earlier conversation summary]", "compacted_count": 32})
    assert _is_internal_leak(body) is True


def test_is_internal_leak_allows_normal_chat():
    assert _is_internal_leak("Here's our menu! 😊") is False
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
.venv/bin/pytest tests/conversation/test_compaction_leak.py -v
```

- [ ] **Step 3: Implement**

In `engine.py`:

```python
def _is_internal_leak(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if "[Earlier conversation summary]" in t and ("compacted_count" in t or t.startswith("{")):
        return True
    if t.startswith("{") and "compacted_count" in t:
        return True
    return False
```

Update `_render_history_content` for `mtype == "system_summary"`:

```python
if mtype == "system_summary":
    summary = (payload.get("summary") or "").strip()
    return summary or "[system_summary]"
```

Update `_build_history` loop: when `msg.type == "system_summary"`, append `{"role": "system", "content": content}` and `continue` (do not use inbound/outbound direction).

Update `_send_text`: if `_is_internal_leak(body)`, log warning, replace body with `"Let me help you with the menu 😊"` (caller may also trigger menu — Task 3).

- [ ] **Step 4: Run tests — expect PASS**

```bash
.venv/bin/pytest tests/conversation/test_compaction_leak.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tests/conversation/test_compaction_leak.py src/app/conversation/engine.py
git commit -m "fix(conversation): compaction summary internal-only; block JSON leak to WhatsApp"
```

---

### Task 2: Intent detectors + dish search handler

**Files:**
- Create: `tests/conversation/test_dish_search.py`
- Modify: `src/app/conversation/engine.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/conversation/test_dish_search.py
import pytest
from app.conversation.engine import (
    _parse_dish_search_query,
    _is_menu_browse_intent,
    handle_inbound,
)
from tests.conversation.conftest import make_text_inbound  # or local helper


def test_parse_dish_search_boneless_chicken():
    assert _parse_dish_search_query("I want to have boneless chicken") == "boneless chicken"


def test_menu_browse_ok_show_me():
    assert _is_menu_browse_intent("OK show me") is True


def test_menu_browse_suggest():
    assert _is_menu_browse_intent("Suggest me something") is True


@pytest.mark.asyncio
async def test_dish_search_sends_matching_dishes(db_session, restaurant, seeded_menu_with_chicken):
    """Text mode: inbound boneless query returns bullet list with at least one dish."""
    conv = ...  # ordering phase
    inbound = make_text_inbound("I want boneless chicken")
    await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    outbound = ...  # last outbox or recorded message
    assert "chicken" in outbound.body.lower()
    assert "AED" in outbound.body
```

- [ ] **Step 2: Run tests — expect FAIL**

```bash
.venv/bin/pytest tests/conversation/test_dish_search.py -v
```

- [ ] **Step 3: Implement detectors + `_handle_dish_search`**

Add near `_parse_category_availability_query`:

```python
_DISH_SEARCH_PATTERNS: tuple[str, ...] = (
    r"^(?:i want|i'd like|id like|looking for|something with)\s+(.+?)[\?\.!]*$",
    r"^(?:give me|show me)\s+(.+?)\s+options?[\?\.!]*$",
)

def _parse_dish_search_query(text: str | None) -> str | None:
    ...

def _is_menu_browse_intent(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t or len(t) > 45:
        return False
    if _is_menu_request(text):
        return True
    browse_phrases = (
        "show me", "ok show me", "suggest", "recommend", "pick for me",
        "what should i order", "surprise me",
    )
    return any(p in t for p in browse_phrases)
```

Add `_handle_dish_search` (copy structure from `_handle_category_availability_query`, match name + `description_customer`, cap `_CATEGORY_REPLY_MAX`).

Wire in `handle_inbound` TEXT block (before AI): if `_parse_dish_search_query(text)` → set `browse_filter` in state → `_handle_dish_search` → return.

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(conversation): dish search + menu browse intent detectors"
```

---

### Task 3: post_order reset + menu browse handler + promise fulfillment

**Files:**
- Create: `tests/conversation/test_menu_browse.py`
- Modify: `src/app/conversation/engine.py`, `src/app/llm/action_schema.py`

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.asyncio
async def test_post_order_show_me_sends_menu(db_session, restaurant, catalogue_enabled):
    conv.state = {"dialogue_phase": "post_order", "dialogue_state": "order_placed"}
    await handle_inbound(db_session, make_text_inbound("OK show me"), restaurant_id=restaurant.id)
    # assert product_list outbox row OR text menu body with dish lines


@pytest.mark.asyncio
async def test_menu_promise_no_action_triggers_catalog(db_session, restaurant, monkeypatch):
    """When AI returns no_action + 'Here\\'s our menu' filler, engine still sends catalogue."""
    ...
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement**

Add `_maybe_reset_post_order_for_browse(conv, text) -> bool`.

Add `_handle_menu_browse` → `_send_menu_or_catalog(prefix="menu-browse", ...)`.

In `handle_inbound`, before AI: if browse intent → reset phase → `_handle_menu_browse` → return.

Extend `_is_menu_request` keywords OR rely on `_is_menu_browse_intent` (preferred separate function).

In `action_schema.py`:

```python
"menu_show": ActionSpec(phases=("ordering", "post_order")),
```

In `_dispatch_action`, before sending `no_action` reply:

```python
_MENU_PROMISE_PATTERNS = ("here's our menu", "let me show you", "take a look", "view full menu")

if action == "no_action" and reply and any(p in reply.lower() for p in _MENU_PROMISE_PATTERNS):
    await _send_menu_or_catalog(session, conv, inbound, restaurant_id, prefix="menu-promise")
    return
```

Phase guard for `show_menu` in post_order: require empty cart via `_build_cart_summary`.

- [ ] **Step 4: Run tests — PASS**

```bash
.venv/bin/pytest tests/conversation/test_menu_browse.py tests/conversation/test_dish_search.py -v
```

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(conversation): post_order browse reset, menu delivery, promise fulfillment"
```

---

### Task 4: Suggestion sub-agent (Approach C)

**Files:**
- Create: `src/app/llm/suggestion_agent.py`, `tests/llm/test_suggestion_agent.py`
- Modify: `src/app/llm/port.py`, `src/app/llm/factory.py`, `src/app/llm/fake.py`, `src/app/conversation/engine.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/llm/test_suggestion_agent.py
import pytest
from app.llm.fake import FakeSuggestionAgent
from app.llm.suggestion_agent import parse_suggestion_response


@pytest.mark.asyncio
async def test_fake_suggestion_returns_picks_from_candidates():
    agent = FakeSuggestionAgent()
    candidates = [{"name": "Chicken Biriyani"}, {"name": "Boneless Chicken Fry"}]
    result = await agent.suggest(candidates, "suggest something", "boneless chicken")
    assert 1 <= len(result["picks"]) <= 3
    assert all(p["dish_name"] in {c["name"] for c in candidates} for p in result["picks"])


def test_parse_rejects_hallucinated_dish():
    raw = '{"intro": "hi", "picks": [{"dish_name": "Fake Dish", "reason": "yum"}]}'
    parsed = parse_suggestion_response(raw)
    assert parsed["picks"][0]["dish_name"] == "Fake Dish"
```

```python
# tests/conversation/test_menu_browse.py (add)
@pytest.mark.asyncio
async def test_suggest_me_something_uses_sub_agent_when_many_matches(...):
    ...
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement `suggestion_agent.py`**

```python
SUGGESTION_SYSTEM = """\
[ROLE] Restaurant menu suggestion assistant.
[TASK] Pick 1-3 dishes from MENU CANDIDATES for the customer request.
[CONSTRAINTS]
- ONLY dish names from candidates; never invent.
- No prices in reasons; max 1 line per reason.
- Output JSON: {"intro": "...", "picks": [{"dish_name": "...", "reason": "..."}]}
"""

async def suggest(self, menu_candidates, customer_text, browse_filter=None) -> dict:
    ...
```

Add `FakeSuggestionAgent` returning first 2 candidates.

Add `get_suggestion_agent()` to factory.

Add `_handle_suggestions` in engine:
- ≤3 candidates → deterministic list
- else → sub-agent → validate with `find_dish_matches` → format + send

Wire: `_is_menu_browse_intent` + "suggest"/"recommend" in text → `_handle_suggestions` (not full menu unless customer says "show menu").

- [ ] **Step 4: Run tests — PASS**

```bash
.venv/bin/pytest tests/llm/test_suggestion_agent.py tests/conversation/test_menu_browse.py -v
```

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(llm): suggestion sub-agent for grounded dish recommendations"
```

---

### Task 5: Prompt alignment (`context.txt` + `conversation_prompts.py`)

**Files:**
- Modify: `context.txt`, `src/app/llm/conversation_prompts.py`
- Test: `tests/llm/test_prompt_goldmine.py`

- [ ] **Step 1: Update MENU / BROWSING blocks in both files**

Add after existing `menu_show` rules:

```
BROWSE / SUGGEST (engine sends real content):
- "show me" / "ok show me" / "suggest" / "recommend" → action="menu_show" with short reply.
- Ingredient browse ("boneless chicken") → name ≤3 REAL dishes from MENU; engine may send list.
- NEVER say "Here's our menu" unless action="menu_show".
- NEVER output JSON, summaries, compacted_count, or internal metadata in reply.

POST_ORDER re-order (empty cart):
- After cancel/delivery, browse/suggest intents follow ORDERING rules above.
```

- [ ] **Step 2: Verify goldmine line count**

```bash
.venv/bin/pytest tests/llm/test_prompt_goldmine.py -v
```

- [ ] **Step 3: Sync prompt KB**

```bash
.venv/bin/python scripts/sync_prompt_kb.py
```

- [ ] **Step 4: Commit**

```bash
git add context.txt src/app/llm/conversation_prompts.py var/prompt_kb/index.json
git commit -m "docs(llm): browse/suggest prompt rules; never leak internal JSON"
```

---

### Task 6: Integration + regression

- [ ] **Step 1: Run conversation regression**

```bash
.venv/bin/pytest tests/conversation/test_menu_browse.py tests/conversation/test_dish_search.py \
  tests/conversation/test_compaction_leak.py tests/conversation/test_compaction.py \
  tests/llm/test_suggestion_agent.py -v
```

- [ ] **Step 2: Run broader smoke**

```bash
.venv/bin/pytest tests/conversation/test_engine_ordering.py tests/conversation/test_engine_full_ai.py -v --tb=short -x
```

- [ ] **Step 3: Lint**

```bash
.venv/bin/ruff check src/app/conversation/engine.py src/app/llm/suggestion_agent.py tests/conversation/test_menu_browse.py
```

- [ ] **Step 4: Graphify update**

```bash
npx graphify . --update
```

- [ ] **Step 5: Update `understanding.txt` log entry**

- [ ] **Step 6: Final commit if loose changes**

```bash
git commit -m "test(conversation): menu browse integration regression green"
```

---

## Plan self-review (spec coverage)

| Spec requirement | Task |
|------------------|------|
| Empty menu promises fixed | Task 3 (browse handler + promise fulfillment) |
| post_order → ordering reset | Task 3 |
| Ingredient search | Task 2 |
| Catalogue + text modes | Tasks 2–3 tests both modes |
| Compaction leak | Task 1 |
| Suggestion sub-agent | Task 4 |
| Prompt alignment | Task 5 |
| Tests | All tasks |

No placeholders remain in task steps above.