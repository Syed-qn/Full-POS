# Prompt Inventory

Where LLM prompts, system instructions, tool-schema guidance, and prompt-injected context live in this codebase.

**Provider selection:** `APP_LLM_PROVIDER` (`deepseek` | `claude` | `fake`) via `src/app/llm/factory.py`.

**Last updated:** 2026-07-02 (full module map — SSOT, sub-agents, context engineering, regression tooling)

**Prompt goldmine (DO NOT DELETE):** [`context.txt`](../context.txt) at repo root — 1600+ lines of original chat prompts (git@800cd53), master-template framework, and current SSOT text.

**Vector KB (runtime):** `app.llm.prompt_kb` chunks `context.txt`, builds a TF-IDF index (`var/prompt_kb/index.json`, auto-rebuilt on change), and injects top-k sections as `[PROMPT_KB]` into the conversation agent system prompt per turn (alongside OKF grounding). Config: `APP_PROMPT_KB_ENABLED` (default true), `APP_PROMPT_KB_TOP_K`, `APP_PROMPT_KB_MAX_CHARS`. Rebuild manually: `python scripts/sync_prompt_kb.py`.

---

## Quick map

```
Customer WhatsApp chat
  └─ src/app/llm/conversation_prompts.py  ← SSOT phase blocks + identity
       (REPLY_DISCIPLINE, REPLY_FIELD_DESCRIPTION, OKF_GROUNDING_RULE, INTENT_BLOCK)
  └─ src/app/llm/deepseek.py              ← DeepSeekConversationAgent assembly only
  └─ src/app/llm/claude.py                ← ClaudeConversationAgent assembly only
  └─ src/app/llm/action_schema.py         ← tool field descriptions (imports REPLY_FIELD_DESCRIPTION)
  └─ src/app/conversation/engine.py       ← runtime context + history + compaction + sub-agent calls
  └─ src/app/okf/retrieval.py             ← RAG grounding_block() injection

Router & completion
  └─ src/app/llm/prompts_router.py        ← W4 router + completion templates

Menu & dishes
  └─ src/app/llm/prompts_menu.py          ← extract, describe, arbitrate, intent, segment, forecast

Kitchen staff digest
  └─ src/app/llm/prompts_kitchen.py       ← TIER2_SYSTEM + build_tier2_user_prompt()
  └─ src/app/llm/kitchen_summary.py       ← build_tier2_prompt() wrapper + parse_tier2_response()

Marketing
  └─ src/app/llm/prompts_marketing.py     ← COPYWRITER_PROMPT
  └─ src/app/marketing/copywriter.py      ← invokes LLM with prompts_marketing

E-10 sub-agents
  └─ src/app/llm/complaint_agent.py       ← _COMPLAINT_SYSTEM + build_complaint_prompt()
  └─ src/app/llm/modify_agent.py          ← _MODIFY_SYSTEM + build_modify_prompt()

E-17 ambiguous intent (ToT-lite)
  └─ src/app/llm/thought_evaluator.py     ← _TOT_SYSTEM + build_tot_prompt()
  └─ src/app/conversation/intent_rubric.py  ← deterministic rubric (no LLM; used first)

Context engineering
  └─ src/app/llm/context_management.py    ← Claude beta context-management config (E-11)
  └─ src/app/conversation/context_metrics.py ← token/char budget snapshots (E-22)
  └─ src/app/conversation/compaction.py   ← history compaction (E-09)

Regression tooling
  └─ scripts/review_prompt_regression.py  ← golden prompt review checklist (E-19)
  └─ scripts/lint_prompt_spec_refs.py     ← spec cross-reference lint (E-24)

Reference docs
  └─ docs/prompt-patterns.md              ← White et al. pattern map (E-18)
  └─ docs/enhancement.md                  ← E-01..E-24 backlog + master template

Tests
  └─ tests/llm/*, tests/conversation/*     ← assertions on prompt content & behavior
```

---

## 1. Customer WhatsApp conversation agent (primary)

Drives the main ordering bot. History is passed as chat messages; system prompt is built per turn.

### Single source of truth (`src/app/llm/conversation_prompts.py`)

| Symbol | Purpose |
|--------|---------|
| `INTENT_BLOCK` | E-23 intent engineering — primary/secondary/never optimize |
| `META_LANGUAGE_BLOCK` | E-06 history prefix semantics (`[customer]`, `[catalog]`, etc.) |
| `IDENTITY_TEMPLATE` | Base persona: restaurant host, multilingual, anti-hallucination |
| `ORDERING_BLOCK_TEMPLATE` | Phase `ordering`: menu, cart, checkout, questions |
| `ADDRESS_BLOCK_TEMPLATE` | Phase `address_capture`: pin, saved address, receiver |
| `CONFIRMATION_BLOCK_TEMPLATE` | Phase `awaiting_confirmation`: summary, confirm, edits |
| `POST_ORDER_BLOCK_TEMPLATE` | Phase `post_order`: acks, status, modify/cancel |
| `CLAUDE_CONVERSATION_SYSTEM` | Claude base system (identity + intent + meta + menu/cart/delivery) |
| `CLAUDE_POST_ORDER_GUIDANCE` | Claude post-order phase guidance |
| `REPLY_DISCIPLINE` | E-04 tool `reply` field rules (injected in `build_identity()`) |
| `REPLY_FIELD_DESCRIPTION` | E-04 short description for `action_schema.py` `reply` field |
| `OKF_GROUNDING_RULE` | E-20 cite/defer rules when grounding block is absent |
| `build_identity()` | Formats identity + intent + meta + reply discipline + OKF rule |
| `build_phase_block(phase)` | Returns phase-specific block from `_PHASE_TEMPLATES` |
| `build_claude_system()` | Claude single system prompt + phase guidance + grounding |

### DeepSeek (`src/app/llm/deepseek.py`) — assembly only

| Symbol | Purpose |
|--------|---------|
| `DeepSeekConversationAgent._build_system()` | `build_identity` + `format_memory_context` + `build_phase_block` + grounding |
| `DeepSeekConversationAgent.respond()` | `_async_chat_tools` with `take_action` tool |

### Claude (`src/app/llm/claude.py`) — assembly only

| Symbol | Purpose |
|--------|---------|
| `ClaudeConversationAgent.respond()` | `build_claude_system()` + `_phase_guidance` + `format_memory_context` + `claude_request_kwargs()` |
| `claude_request_kwargs()` | E-11 server-side tool-result clearing (via `context_management.py`) |

### Tool schema (acts as mini-prompts)

`src/app/llm/action_schema.py` — single source of truth for the `take_action` tool:

| Symbol | Purpose |
|--------|---------|
| `ACTION_SPECS` | Canonical action vocabulary + per-phase allowlists |
| `build_tool_properties()` | JSON-schema field descriptions (`action`, `add_qty`, `reply`, etc.) |
| `build_openai_tool()` | DeepSeek/OpenAI wrapper |
| `build_anthropic_tool()` | Claude wrapper |

**Note:** Phase blocks live in `conversation_prompts.py`. Providers only assemble + inject runtime context.

---

## 2. Intent routing & completion detection

| File | Symbol | Purpose |
|------|--------|---------|
| `prompts_router.py` | `ROUTER_CLASSIFY_TEMPLATE` | W4 top-level router (multilingual intent) |
| `prompts_router.py` | `COMPLETION_DETECT_TEMPLATE` | "Is customer finished ordering?" → yes/no |
| `deepseek.py` | `DeepSeekRouterClassifier` | Fills router template, calls DeepSeek |
| `claude.py` | `ClaudeRouterClassifier` | Same (Claude haiku) |
| `deepseek.py` | `DeepSeekCompletionDetector` | Completion template |
| `claude.py` | `ClaudeCompletionDetector` | Same |

### Fake router (not LLM)

`src/app/llm/router_fake.py` — token/heuristic sets for tests.

---

## 3. Menu & dish LLM tasks

| File | Symbol | Purpose |
|------|--------|---------|
| `prompts_menu.py` | `EXTRACT_SYSTEM` | Menu digitization → JSON dish array |
| `prompts_menu.py` | `DESCRIBE_DISH_TEMPLATE` | Customer-facing description ≤3 lines, no price |
| `prompts_menu.py` | `ARBITRATE_TEMPLATE` | Pick best dish match from candidates |
| `prompts_menu.py` | `INTENT_CLASSIFY_TEMPLATE` | Legacy intent classifier |
| `prompts_menu.py` | `SEGMENT_COMPILE_TEMPLATE` | Plain English → segment DSL JSON |
| `prompts_menu.py` | `FORECAST_OVERRIDE_TEMPLATE` | Manager note → `parsed_effect` JSON |
| `deepseek.py` / `claude.py` | Extractor/Describer/Arbiter/Segment/Forecast classes | Invoke templates |

---

## 4. Kitchen digest (staff-facing)

Tier 1 = deterministic code (`render_structured_lines`). Tier 2 = LLM supplement.

| File | Symbol | Purpose |
|------|--------|---------|
| `prompts_kitchen.py` | `TIER2_SYSTEM` | Extract 0–2 net-new kitchen/delivery lines |
| `prompts_kitchen.py` | `build_tier2_user_prompt()` | User turn: authoritative block + customer chat |
| `kitchen_summary.py` | `build_tier2_prompt()` | Thin wrapper → `build_tier2_user_prompt()` |
| `kitchen_summary.py` | `parse_tier2_response()` | Parse tier-2 output |
| `deepseek.py` / `claude.py` | `*KitchenSummarizer` | Production LLM calls |

---

## 5. Marketing

| File | Symbol | Purpose |
|------|--------|---------|
| `prompts_marketing.py` | `COPYWRITER_PROMPT` | Manager offer → Meta WhatsApp template JSON |
| `marketing/copywriter.py` | `draft_template()` | Invokes LLM; `_fallback()` on failure |

Segment DSL and forecast override prompts live in `prompts_menu.py` (see §3).

---

## 6. E-10 sub-agents

Focused LLM calls with order + chat context; main agent delegates distillation.

### Complaint (post-delivery)

| File | Symbol | Purpose |
|------|--------|---------|
| `complaint_agent.py` | `_COMPLAINT_SYSTEM` | Distill complaint → `{issue, suggested_action}` JSON |
| `complaint_agent.py` | `build_complaint_prompt()` | ORDER CONTEXT + CHAT SNIPPET user turn |
| `complaint_agent.py` | `parse_complaint_response()` | JSON validation + action allowlist |
| `complaint_agent.py` | `build_order_context_for_summarizer()` | Compact order facts for prompt |
| `complaint_agent.py` | `build_chat_snippet_for_summarizer()` | Recent customer messages for prompt |
| `engine.py` | `_handle_complaint()` | Calls `get_complaint_summarizer()`, stores evidence on ticket |

### Modify (order line changes)

| File | Symbol | Purpose |
|------|--------|---------|
| `modify_agent.py` | `_MODIFY_SYSTEM` | Distill modify proposal → `{summary, change_count, suggested_action}` JSON |
| `modify_agent.py` | `build_modify_prompt()` | ORDER CONTEXT + PROPOSED CHANGES + CHAT SNIPPET user turn |
| `modify_agent.py` | `parse_modify_response()` | JSON validation + action allowlist |
| `modify_agent.py` | `format_proposed_lines()` | Render proposed line items for prompt |
| `engine.py` | `_handle_modify_intent()` / `_handle_modify_items()` | Calls `get_modify_summarizer()` |

---

## 7. E-17 ToT-lite thought evaluator

Resolves ambiguous router `UNKNOWN` turns. Deterministic rubric runs first; LLM fallback only when rubric returns `None`.

| File | Symbol | Purpose |
|------|--------|---------|
| `thought_evaluator.py` | `_TOT_SYSTEM` | Score add \| question \| checkout candidates |
| `thought_evaluator.py` | `build_tot_prompt()` | Phase + cart + message + candidates user turn |
| `thought_evaluator.py` | `parse_tot_response()` | JSON validation → `{winner, confidence}` |
| `thought_evaluator.py` | `DeterministicThoughtEvaluator` | Rubric-only path (no LLM) |
| `thought_evaluator.py` | `DeepSeekThoughtEvaluator` / `ClaudeThoughtEvaluator` | Production LLM fallback |
| `intent_rubric.py` | `resolve_ambiguous_intent()` | Checkout/done phrase detection (extracted from engine) |
| `engine.py` | E-17 branch in ordering path | `get_thought_evaluator().evaluate()` when router is `UNKNOWN` |

---

## 8. Context engineering (E-09, E-11, E-22)

| File | Symbol | Purpose |
|------|--------|---------|
| `compaction.py` | `build_compact_summary()` | Deterministic digest of compacted turns |
| `compaction.py` | `maybe_compact_history()` | Threshold-based history compaction (E-09) |
| `context_management.py` | `build_context_management_config()` | Claude beta `context-management-2025-06-27` payload (E-11) |
| `context_management.py` | `format_memory_context()` | Inject `[MEMORY]` session notes outside history window |
| `context_management.py` | `claude_request_kwargs()` | Extra kwargs for `beta.messages.create` |
| `context_metrics.py` | `build_context_snapshot()` | Char/token budget snapshot (E-22) |
| `context_metrics.py` | `log_context_snapshot()` | Ops logging before each agent turn |

---

## 9. Runtime context injection (not prompts — fed into prompts)

Assembled in `src/app/conversation/engine.py` and appended into conversation system prompts.

| Function | Injected keys / output |
|----------|------------------------|
| `_build_context()` | `menu_text`, `cart_summary`, `cart_lines`, `delivery_info`, `hours_info`, `saved_address`, JIT menu (E-03), session notes (E-05), etc. |
| `_build_history()` | Per-phase window (E-01), source prefixes (E-06), compaction (E-09), cart dedup (E-22) |
| `_hours_info()` | Opening-hours line from restaurant settings |
| `_okf_grounding()` | Calls OKF retrieval → `context["grounding"]` |
| `okf/retrieval.py` → `grounding_block()` | Renders docs with cap/priority/cites (E-08, E-20) |
| `log_context_snapshot()` | Pre-turn budget metrics (E-22) |

---

## 10. Test doubles (no real LLM prompts)

| File | Class | Notes |
|------|-------|-------|
| `llm/fake.py` | `FakeConversationAgent` | Rule-based phase behavior |
| `llm/fake.py` | `FakeComplaintSummarizer` | Deterministic complaint distillation |
| `llm/fake.py` | `FakeModifySummarizer` | Deterministic modify distillation |
| `llm/fake.py` | `FakeThoughtEvaluator` | Rubric-only ToT-lite (via `intent_rubric`) |
| `llm/fake.py` | `FakeExtractor`, `FakeDescriber`, etc. | Other stubs |
| `llm/router_fake.py` | Token classifier | Stand-in for `RouterClassifier` |

---

## 11. Tests that assert on prompts

| File | What it checks |
|------|----------------|
| `tests/llm/test_conversation_prompts.py` | SSOT blocks, section tags, phase assembly, E-04 reply discipline |
| `tests/llm/test_auxiliary_prompts.py` | Menu/router/kitchen/marketing template exports |
| `tests/llm/test_deepseek_prompt.py` | DeepSeek system prompt structure |
| `tests/llm/test_location_grounding.py` | Location, fees, hours, no-invent rules |
| `tests/llm/test_address_guardrails.py` | `ADDRESS_BLOCK_TEMPLATE` guardrails |
| `tests/llm/test_cart_state_prompt_precedence.py` | Cart authority + Claude system |
| `tests/llm/test_complaint_agent.py` | E-10 complaint prompt + fake summarizer |
| `tests/llm/test_kitchen_summary.py` | `build_tier2_prompt()` shape |
| `tests/conversation/test_context_engineering.py` | E-01/E-03/E-05/E-06/E-21/E-22 |
| `tests/conversation/test_compaction.py` | E-09 history compaction |
| `tests/conversation/test_modify_post_order.py` | Post-order modify flow (uses modify sub-agent) |
| `tests/conversation/test_modify_global_intents.py` | Modify intent routing |
| `tests/okf/test_retrieval_cap.py` | E-08/E-20 OKF grounding cap |
| `tests/marketing/test_copywriter.py` | Emoji/dash formatting on drafted templates |

---

## 12. Documentation copies (reference only — not runtime)

Edit **source files** above, not these, for behavior changes:

- `docs/superpowers/plans/2026-06-10-full-ai-conversation-agent.md`
- `docs/enhancement.md` — context engineering backlog E-01..E-24
- `docs/prompt-patterns.md` — White et al. pattern catalog map

---

## Edit cheat sheet

| Want to change… | Edit here |
|-----------------|-----------|
| Bot personality / never-invent rules | `conversation_prompts.py` `IDENTITY_TEMPLATE` |
| Intent priorities when rules conflict | `conversation_prompts.py` `INTENT_BLOCK` |
| Cart add/remove/checkout behavior | `ORDERING_BLOCK_TEMPLATE` |
| Address capture flow | `ADDRESS_BLOCK_TEMPLATE` |
| Order confirm step | `CONFIRMATION_BLOCK_TEMPLATE` |
| Post-order "Ok" / status / modify | `POST_ORDER_BLOCK_TEMPLATE` |
| Tool reply discipline | `REPLY_DISCIPLINE` + `REPLY_FIELD_DESCRIPTION` in `conversation_prompts.py` |
| Which actions the model may call | `action_schema.py` `ACTION_SPECS` |
| RAG / grounded facts | `okf/retrieval.py`; engine `_okf_grounding()` |
| History window / prefixes / compaction | `engine.py` `_build_history`, `config.py`, `compaction.py` |
| Claude server-side context clearing | `context_management.py`; `config.py` `claude_context_management_*` |
| Context budget logging | `context_metrics.py`; engine pre-turn snapshot |
| Marketing template AI draft | `prompts_marketing.py` `COPYWRITER_PROMPT` |
| Kitchen chat supplement | `prompts_kitchen.py` `TIER2_SYSTEM` |
| Intent router / completion | `prompts_router.py` templates |
| Complaint distillation | `complaint_agent.py` `_COMPLAINT_SYSTEM` |
| Modify distillation | `modify_agent.py` `_MODIFY_SYSTEM` |
| Ambiguous intent (ToT-lite) | `thought_evaluator.py` `_TOT_SYSTEM`; `intent_rubric.py` rubric |
| Segment DSL / forecast override | `prompts_menu.py` `SEGMENT_COMPILE_TEMPLATE` / `FORECAST_OVERRIDE_TEMPLATE` |

---

## Provider parity checklist

When changing conversation behavior:

1. Update `conversation_prompts.py` (canonical SSOT).
2. Verify `deepseek.py` and `claude.py` assembly still import from SSOT.
3. Update `action_schema.py` if tool fields or action semantics change.
4. Run `tests/llm/test_conversation_prompts.py`, `test_address_guardrails.py`, `test_cart_state_prompt_precedence.py`, `tests/conversation/test_context_engineering.py`.
5. Run `python scripts/lint_prompt_spec_refs.py` on edited prompt files.
6. Update this doc if symbols/locations shift.