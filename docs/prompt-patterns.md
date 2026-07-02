# Prompt Pattern Catalog (E-18)

Maps [White et al. Prompt Pattern Catalog](https://arxiv.org/abs/2302.11382) patterns to each prompt type in this codebase. Use this when editing prompts so pattern composition stays intentional — not ad hoc.

**Related:** [enhancement.md](./enhancement.md) · [prompt-inventory.md](./prompt-inventory.md)

---

## Fundamental contextual statements

Per White et al. §II-D, prefer stable meta-language over brittle grammars:

> “When I say X, I mean Y (or would like you to do Y).”

Our informal history prefixes (`[Cart updated]`, `[catalog]`, `[tapped: …]`, `[sent catalogue basket: …]`) are **Meta Language Creation** — document any new prefix in `META_LANGUAGE_BLOCK` (and engine `_render_history_content`) before using it in production.

---

## Pattern map by prompt type

| Prompt type | Primary patterns | Secondary patterns | Output contract |
|-------------|------------------|--------------------|-----------------|
| **Conversation agent** (`IDENTITY_TEMPLATE`, phase blocks in `conversation_prompts.py`) | Persona, Recipe, Context Manager | Constraint (via NEVER/ALWAYS), Cognitive Verifier (engine validates tool args) | `take_action` tool JSON |
| **Kitchen tier-2** (`prompts_kitchen.TIER2_SYSTEM`) | Persona, Output format | Fact Check List (authoritative block is ground truth) | 0–2 lines or `NONE` |
| **Complaint sub-agent** (`complaint_agent._COMPLAINT_SYSTEM`) | Persona, Template | Fact Check List, Reflection (no compensation promises) | JSON `{issue, suggested_action}` |
| **Modify sub-agent** (`modify_agent._MODIFY_SYSTEM`) | Persona, Template | Fact Check List, Reflection (no refund promises) | JSON `{summary, change_count, suggested_action}` |
| **Thought evaluator (E-17)** (`thought_evaluator._TOT_SYSTEM`) | Recipe (score candidates) | Alternative Approaches (add \| question \| checkout) | JSON `{winner, confidence}` |
| **Router classifier** (`prompts_router.ROUTER_CLASSIFY_TEMPLATE`) | Persona, Context Manager | Recipe (single-label decision) | One `IntentLabel` token |
| **Completion detector** (`prompts_router.COMPLETION_DETECT_TEMPLATE`) | Persona, Recipe | Cognitive Verifier (exclude dish names) | `yes` / `no` |
| **Menu extractor** (`prompts_menu.EXTRACT_SYSTEM`) | Persona, Template | Fact Check List (no invented dishes) | JSON dish array |
| **Dish describer** (`prompts_menu.DESCRIBE_DISH_TEMPLATE`) | Persona, Template | Constraint (≤3 lines, no price) | Plain text |
| **Dish arbiter** (`prompts_menu.ARBITRATE_TEMPLATE`) | Persona, Recipe | Alternative Approaches (implicit in candidate list) | Dish id or none |
| **Marketing copywriter** (`prompts_marketing.COPYWRITER_PROMPT`) | Persona, Template | Output Automater (JSON for downstream submit) | JSON `{body, footer}` |
| **Segment compiler** (`prompts_menu.SEGMENT_COMPILE_TEMPLATE`) | Meta Language Creation (DSL), Template | Fact Check List (`validate_dsl`) | Segment DSL JSON |
| **Forecast adjuster** (`prompts_menu.FORECAST_OVERRIDE_TEMPLATE`) | Meta Language Creation (`parsed_effect` DSL), Template | — | `parsed_effect` JSON |

---

## Per-type detail

### Conversation agent → Persona + Recipe + Constraint + Tool contract

| Pattern | Application |
|---------|-------------|
| **Persona** | `IDENTITY_TEMPLATE`: warm restaurant host, multilingual, brand voice |
| **Recipe** | Phase blocks (`ORDERING_BLOCK_TEMPLATE` DECISION ORDER, `ADDRESS_BLOCK_TEMPLATE` steps 1–6) |
| **Context Manager** | Phase FSM + `_build_context()` injects cart, menu, address, hours |
| **Template** | `take_action` tool schema field descriptions in `action_schema.py` |
| **Constraint** | NEVER INVENT, cart authority (R-072), phase action allowlists |
| **Meta Language** | `META_LANGUAGE_BLOCK`; cart observations in engine history render |
| **Intent** | `INTENT_BLOCK` (E-23) — primary/secondary/never optimize when rules conflict |

**Do not add:** Output Automater (engine executes actions), Flipped Interaction (engine drives address FSM).

### Kitchen tier-2 → Persona + Output format

| Pattern | Application |
|---------|-------------|
| **Persona** | Kitchen/delivery staff assistant |
| **Template** | `build_tier2_user_prompt()` — `AUTHORITATIVE BLOCK` + `CUSTOMER CHAT` user turn |
| **Fact Check List** | Tier-1 structured lines are authoritative; tier-2 only adds net-new |
| **Output format** | Exactly `NONE` or 0–2 plain lines, customer language preserved |

### Complaint sub-agent → Persona + Template + JSON output

| Pattern | Application |
|---------|-------------|
| **Persona** | Staff handoff analyst — classify, never compensate |
| **Template** | `ORDER CONTEXT` + `CHAT SNIPPET` slots |
| **Reflection** | `suggested_action` enum routes to human for refunds |
| **Constraint** | No invented items; no refund/credit promises in output |

### Modify sub-agent → Persona + Template + JSON output

| Pattern | Application |
|---------|-------------|
| **Persona** | Order-modification distiller for staff handoff |
| **Template** | `ORDER CONTEXT` + `PROPOSED CHANGES` + optional `CHAT SNIPPET` |
| **Reflection** | `suggested_action` enum routes clarify vs confirm vs escalate |
| **Constraint** | No invented dishes; escalate on refund/compensation language |

### Thought evaluator (E-17) → Recipe + Alternative Approaches

| Pattern | Application |
|---------|-------------|
| **Recipe** | Score three candidates (add, question, checkout) and pick winner |
| **Alternative Approaches** | Explicit candidate list in `build_tot_prompt()` |
| **Cognitive Verifier** | `intent_rubric.resolve_ambiguous_intent()` runs first (deterministic) |
| **Constraint** | Checkout only when customer clearly means finished ordering |

**Default path:** deterministic rubric only. LLM (`_TOT_SYSTEM`) is fallback when rubric returns `None`.

### Marketing copywriter → Persona + Template + JSON output

| Pattern | Application |
|---------|-------------|
| **Persona** | Restaurant marketing writer |
| **Template** | `{{1}}` name placeholder, footer opt-out |
| **Constraint** | Meta template compliance (length, emoji, no short URLs) |

### Segment compiler → Meta-language (DSL) + JSON-only

| Pattern | Application |
|---------|-------------|
| **Meta Language Creation** | Segment DSL fields/ops taught in prompt |
| **Template** | JSON schema with `all` / `any` trees |
| **Fact Check List** | `validate_dsl()` rejects unsafe output |

---

## Patterns we deliberately omit on the live path

| Pattern | Why omitted | Where instead |
|---------|-------------|---------------|
| **Tree of Thoughts (full)** | Latency; happy path is single-shot | E-17 ToT-lite on router `UNKNOWN` only — **implemented** (`thought_evaluator.py` + `intent_rubric.py`) |
| **Flipped Interaction** | Address/menu flows are engine FSM | `engine.py` deterministic steps |
| **Output Automater** | LLM must not run scripts | Engine executes `take_action` |
| **Infinite Generation** | Single reply per customer turn | — |
| **Game Play** | Not appropriate for ordering | — |

---

## Composition rules (from enhancement.md + White et al.)

1. **Start minimal** — add patterns only for observed failure modes.
2. **Combine intentionally** — Persona + Recipe + Context Manager is the default stack for the conversation agent.
3. **Avoid ambiguous meta-language** — comma semantics can change meaning (paper §II-D); use explicit prefixes in `META_LANGUAGE_BLOCK`.
4. **Separate intent from constraints** — E-23 `INTENT_BLOCK` (implemented) vs NEVER/ALWAYS constraint lines.
5. **Link rules to specs** — new NEVER/ALWAYS lines need `# spec:` traceability (E-24, `lint_prompt_spec_refs.py`).

---

## Checklist before editing a prompt

- [ ] Which patterns does this prompt type use (table above)?
- [ ] Is the change a **Persona** tweak, **Recipe** step, or **Constraint**?
- [ ] Can the engine handle it deterministically instead (shorter prompt)?
- [ ] Is the rule duplicated in engine + prompt?
- [ ] Is there a failing regression test?
- [ ] Does `review_prompt_regression.py` pass on the edited file?
- [ ] Do new NEVER/ALWAYS lines include `# spec: §…`?