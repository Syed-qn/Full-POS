# Context Engineering Enhancements

Actionable improvements for the WhatsApp restaurant agent, grounded in industry guidance, academic research on advanced prompting, and a **master prompt** structure — all mapped to this codebase.

**Primary references:**

- [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) — Anthropic, Sep 2025
- [Context Engineering: From Prompts to Corporate Multi-Agent Architecture](https://arxiv.org/abs/2603.09619) — Vishnyakova, Mar 2026 (v2)
- [A Prompt Pattern Catalog](https://arxiv.org/abs/2302.11382) — White et al., Feb 2023 (local: `2302.11382v1.pdf`)
- [PromptPilot](https://arxiv.org/abs/2510.00555) — Gutheil et al., ICIS 2025 (local: `2510.00555v1.pdf`)
- [Tree of Thoughts](https://arxiv.org/abs/2305.10601), [KG-integrated reasoning](https://arxiv.org/abs/2402.04978)
- Master prompt component framework (ROLE → OUTPUT FORMAT)

**Related internal doc:** [prompt-inventory.md](./prompt-inventory.md)

**Last updated:** 2026-07-02 (PDF deep-read v2: Pattern Catalog, PromptPilot, Vishnyakova — full Table I, study protocol, ADK/ACE/Tomasev)

---

## Source summary (Anthropic)

### Context engineering vs. prompt engineering

| Prompt engineering | Context engineering |
|--------------------|---------------------|
| Wording and structure of instructions | **Full token budget** per inference: system prompt, tools, MCP, external data, message history |
| Often one-shot classification / generation | Multi-turn agents over longer horizons |
| “What should the system prompt say?” | “What configuration of context maximizes desired behavior **this turn**?” |

Context curation is **iterative** — not a one-time design artifact.

### Why context is scarce

- **Context rot:** recall and precision degrade as token count grows ([Chroma research](https://research.trychroma.com/context-rot)).
- Transformers attend **all-pairs** across the window; attention budget is finite.
- Training distributions favor shorter sequences; long-context use is harder.

**Guiding principle:** find the **smallest set of high-signal tokens** that still reliably produce the desired outcome.

### Anatomy of effective context

1. **System prompts** — clear language at the “right altitude” (not brittle if/else prose, not vague hand-waving). Organize into sections. Start minimal; add rules for **observed** failure modes only.
2. **Tools** — token-efficient, self-contained, minimal overlap. If a human can’t pick the right tool, the agent can’t either.
3. **Examples** — few diverse canonical examples, not a laundry list of edge-case rules.
4. **Retrieval** — prefer **just-in-time** loading (references + tools) over stuffing everything upfront; hybrid works when content is semi-static.
5. **Long horizons** — compaction, structured note-taking (external memory), sub-agent summaries.

---

## Academic research — advanced prompting & context

Six sources (four arXiv + Anthropic + Vishnyakova synthesis) that inform prompt structure, context pipelines, and enterprise agent maturity.

### 1. Tree of Thoughts (ToT)

**Paper:** [Tree of Thoughts: Deliberate Problem Solving with Large Language Models](https://arxiv.org/abs/2305.10601)  
**Authors:** Shunyu Yao, Dian Yu, Jeffrey Zhao, Izhak Shafran, Thomas L. Griffiths, Yuan Cao, Karthik Narasimhan (NeurIPS 2023)  
**Code:** [princeton-nlp/tree-of-thought-llm](https://github.com/princeton-nlp/tree-of-thought-llm)

**Core idea:** Generalizes Chain-of-Thought by letting the model explore **multiple reasoning paths** as a tree. Intermediate “thoughts” are evaluated; the model can branch, proceed, or **backtrack** before committing to an answer.

**Relevance here:**

| ToT concept | Our analogue | Gap |
|-------------|--------------|-----|
| Multiple candidate thoughts | `DeepSeekArbiter` / `ClaudeArbiter` for dish match | Single-shot pick, no explicit backtrack |
| Self-evaluation of intermediate steps | `take_action` + `to_engine_result` validation | Engine rejects bad tool calls; model doesn’t re-plan |
| Deliberate search | Deterministic engine guards before LLM | Good — reduces need for full ToT on happy path |

**Enhancement hook:** E-17 (ToT-lite for ambiguous orders) — see backlog.

---

### 2. A Prompt Pattern Catalog (full inventory)

**Paper:** [A Prompt Pattern Catalog to Enhance Prompt Engineering with ChatGPT](https://arxiv.org/abs/2302.11382)  
**PDF:** `2302.11382v1.pdf`  
**Authors:** Jules White, Quchen Fu, Sam Hays, Michael Sandborn, Carlos Olea, Henry Gilbert, Ashraf Elnashar, Jesse Spencer-Smith, Douglas C. Schmidt (Vanderbilt)

**Core idea:** Prompts are a form of **programming** LLMs. Document them as **prompt patterns** — reusable solutions analogous to software design patterns, combinable in one prompt. Patterns use **fundamental contextual statements** (not rigid grammars): “When I say X, I mean Y.”

**Fundamental contextual statements** (paper §II-D — preferred over rigid grammars):

> “When I say X, I mean Y (or would like you to do Y).”

Ideas can be reworded; the **key ideas** stay stable. Our `[Cart updated]`, `[catalog]`, `[tapped: …]` prefixes are informal meta-language — document them explicitly (E-18) to avoid ambiguous comma semantics (paper’s Marie Antoinette / indefinite-article example).

**Full Table I — 16 patterns in 6 categories:**

| Category | Pattern | One-line intent |
|----------|---------|-----------------|
| **Input Semantics** | Meta Language Creation | Teach the LLM a custom shorthand or notation |
| **Output Customization** | Output Automater | LLM output includes runnable automation (scripts) |
| | Persona | Fixed role/voice for generation |
| | Visualization Generator | Textual output for downstream visual tools |
| | Recipe | Numbered steps to reach a stated end state |
| | Template | Fill-in structure the LLM completes |
| **Error Identification** | Fact Check List | Output includes facts the user must verify |
| | Reflection | LLM introspects and flags its own errors |
| **Prompt Improvement** | Question Refinement | LLM suggests a better version of the user’s question |
| | Alternative Approaches | LLM proposes other ways to accomplish the task |
| | Cognitive Verifier | LLM asks sub-questions before answering the whole |
| | Refusal Breaker | LLM rewords the question when it would refuse |
| **Interaction** | Flipped Interaction | LLM asks questions until it has enough to act |
| | Game Play | Output framed as a game |
| | Infinite Generation | Regenerate output without re-entering the prompt |
| **Context Control** | Context Manager | User specifies the context the LLM should assume |

**Pattern form** (for `docs/prompt-patterns.md`): name + classification, intent, motivation, structure/key ideas, example implementation, consequences — analogous to software design patterns.

**Canonical example from paper (Flipped Interaction + deployment):**

> “From now on, I would like you to ask me questions to deploy a Python application to AWS. When you have enough information, create a Python script to automate the deployment.”

**Patterns mapped to this codebase:**

| Pattern | Our implementation | Gap |
|---------|-------------------|-----|
| **Persona** | `_IDENTITY` host voice | ✓ |
| **Recipe** | `_ADDRESS_BLOCK` 1–6; `_ORDERING_BLOCK` DECISION ORDER | ✓ |
| **Template** | `take_action` tool schema; marketing `{{1}}` template | ✓ |
| **Meta Language Creation** | `[Cart updated]`, `[catalog]`, `[tapped: …]` in history render | Partial — not documented as meta-language |
| **Flipped Interaction** | Address capture asks one field at a time (engine + prompt) | Engine-driven, not LLM-flipped |
| **Cognitive Verifier** | `to_engine_result` required-field validation | Deterministic, not LLM sub-questions |
| **Question Refinement** | — | Not used — could improve vague customer msgs |
| **Context Manager** | Phase FSM + `_build_context()` | Strong — context varies by phase |
| **Fact Check List / Reflection** | OKF grounding + “NEVER INVENT” | Partial — no explicit reflection step |
| **Output Automater** | Engine executes `take_action` (not LLM scripts) | Correct separation for production |

**Paper guidance:** Patterns combine; start minimal; avoid ambiguous meta-language (comma semantics example in paper). Tested originally with ChatGPT; our port is DeepSeek/Claude function-calling.

**Enhancement hooks:** E-12, E-18, **E-21** (Question Refinement for vague inbound) — see backlog.

**Further:** [Prompt Engineering Guide — papers](https://www.promptingguide.ai/papers) · [ACM pattern catalog](https://dl.acm.org/doi/10.5555/3721041.3721046)

---

### 3. PromptPilot (LLM-enhanced prompt engineering)

**Paper:** [PromptPilot: Improving Human-AI Collaboration Through LLM-Enhanced Prompt Engineering](https://arxiv.org/abs/2510.00555)  
**PDF:** `2510.00555v1.pdf`  
**Authors:** Niklas Gutheil, Valentin Mayer, Leopold Müller, Jörg Römmelt, Niklas Kühl (ICIS 2025)  
**Code:** [FraunhoferFITBusinessInformationSystems/PromptPilot](https://github.com/FraunhoferFITBusinessInformationSystems/PromptPilot)

**Core idea:** Handbooks and silent optimization pipelines fail non-experts. **PromptPilot** is an interactive assistant that diagnoses draft prompts, asks **guided questions**, proposes an improved master prompt, shows a **change summary**, and leaves the user in control.

**Four design objectives (DO1–DO4):**

| DO | Requirement | PromptPilot UI behavior |
|----|-------------|-------------------------|
| **DO1** | Indicate improvement potential in a specific **error domain** | Flags gaps: target audience, purpose, structure, specificity, language |
| **DO2** | Goal-oriented guidance; automate collection of missing info | Guided questions before task execution |
| **DO3** | Signal when refinement is **complete** | Summary of improvements; “further editing is final” |
| **DO4** | **User autonomy** — suggested prompt is always editable | User may revise and submit own version |

**DSR process:** Problem → DO1–DO4 → build PromptPilot → pre-study (n=44) → main RCT (n=80, Prolific, 40/40 split) → EVAL 1–4 (Sonnenberg & vom Brocke).

**Study protocol:**

- **Task LLM:** LLaMA 3.1 70B (both PromptPilot assistant and final task execution).
- **Judge:** GPT-4o via LangChain `LabeledScoreStringEvalChain` (helpfulness, relevance, correctness, depth, detail); benchmark from GPT-4.5, manually verified.
- **UI:** Part 1 = assignment (no copy-paste); Part 2 = one-shot prompt chat (+ PromptPilot for treatment); Part 3 = final answer required before “next”.
- **Three work tasks** (consulting-style, similar complexity): (1) social-media thread for an AI market-research tool, (2) customer persona for eco-friendly care product, (3) blog short-story as fiction author.

**Results (n=80, RCT):** Aggregate median **78.3** [IQR 28.1] vs control **61.7** [44.2] — Mann–Whitney U=1038, p=.045 Holm, Cohen’s d=0.56. **Task 1 only** significant after correction (85.0 vs 55.0, padj=.045); tasks 2–3 not. Means: treatment 70.53 (SD 19.40) vs control 57.45 (SD 26.32).

**DO1 error domains** (what PromptPilot diagnoses before guided questions):

- Missing **target audience** or **purpose** of request  
- Weak **structure** (sections, flow)  
- Low **specificity** (constraints, success criteria)  
- Poor **language** (tone, clarity, jargon)  

**Treatment UX flow:** draft prompt → domain flags (DO1) → guided questions (DO2) → change summary + “further editing is final” (DO3) → editable suggested prompt (DO4).

**Relevance here (dev-time, not customer-facing):**

| PromptPilot concept | Our analogue |
|--------------------|--------------|
| Error domain diagnosis | Failing pytest + customer transcript |
| Guided questions | Code review checklist for prompt PRs |
| Completion signal | “Prompt parity tests green” before merge |
| User autonomy | Human merges; never auto-edit production prompts |

**Enhancement hook:** E-19 — `scripts/review_prompt_regression.py` implementing DO1–DO4 for `_ORDERING_BLOCK` / `_POST_ORDER_BLOCK` edits.

---

### 4. Knowledge Graph–integrated collaboration

**Paper:** [An Enhanced Prompt-Based LLM Reasoning Scheme via Knowledge Graph-Integrated Collaboration](https://arxiv.org/abs/2402.04978)  
**Authors:** Yihao Li, Ru Zhang, Jianyi Liu

**Core idea:** LLMs hallucinate and lack transparent reasoning. The scheme **iteratively explores a Knowledge Graph**, retrieves a **task-relevant subgraph**, then reasons over that subgraph while **explicitly tracing** steps — training-free, no fine-tuning.

**Relevance here:** Our **OKF** (`okf/`) + `graphify-out/` knowledge graph is the same architectural family:

| KG paper | Our stack |
|----------|-----------|
| Task-relevant subgraph retrieval | `okf/retrieval.retrieve()` — entity pins + lexical match |
| Ground reasoning in verified facts | `grounding_block()` appended last in system prompt |
| Traceable reasoning | Engine FSM + audit log; LLM step is opaque today |

**Enhancement hook:** E-08 (OKF cap), E-20 (OKF as explicit subgraph per turn, cite doc `kind` in prompt) — strengthens KG collaboration without new infra.

**Related surveys:** [arXiv:2308.10620](https://arxiv.org/html/2308.10620v5) (prompt engineering surveys)

---

### 5. Context Engineering — corporate multi-agent architecture (Vishnyakova)

**Paper:** [Context Engineering: From Prompts to Corporate Multi-Agent Architecture](https://arxiv.org/abs/2603.09619)  
**PDF:** `2603.09619v2.pdf` (HSE University, March 2026, 25 pp.)  
**Author:** Vera V. Vishnyakova

**Core idea:** Prompt engineering remains the **foundation** (not dead), but autonomous agents need **context engineering (CE)** — designing the full informational environment: memory, policies, tool outputs, history, visibility boundaries. Context is the agent’s **operating system**. Higher layers: **intent engineering (IE)** (trade-off hierarchies) and **specification engineering (SE)** (machine-readable policy corpus).

**Three deployment levels** (paper §4):

| Level | Who builds agent | Context manager | Our position |
|-------|------------------|-----------------|--------------|
| **L1** LLM-as-service | Vendor | Human per turn | Dev/tests with raw API |
| **L2** Vendor agentic product | Vendor (hidden orchestrator) | Vendor | — |
| **L3** Enterprise agent | Company | Company designs pipeline | **This platform** — `engine.py`, `take_action`, tenant memory, spec/OKF |

**CE definition (operational):** manage composition, timing, representation format, and **lifespan** of information — **JIT knowledge logistics** (what/when/how long/for which sub-agent). Context = agent **OS** (memory alloc, isolation, external interfaces), not a passive prompt buffer.

**Three CE deficits** the OS must manage: **relevance** (minimum sufficient slice), **memory** (finite window + external store), **budget** (token cost/latency).

**Google ADK three-tier stack** (paper §8): storage (long-term state/artifacts) → processor pipeline (compress/filter/enrich) → **compiled working context** (what the model actually sees). Our analogue: DB + OKF → `_build_history` / compaction → `_build_context()` + phase prompt.

**ACE framework** (Zhang et al.): contexts as **evolving playbooks** — generate, reflect, curate; retain what works. Maps to iterative prompt/spec refinement after production transcripts (E-19, E-24).

**Tomasev intelligent delegation** (paper §8): **contract-first decomposition** — delegate only when result is verifiable; else recurse. **Authority gradient** — under-specified tasks + sycophantic sub-agents → false “data sufficient” failures. **Delegation ≠ decomposition** — sub-agent gets authority + accountability, not just a task chunk. Kitchen tier-2 + post-order modify are partial delegation; coordinator should receive verdict + confidence, not raw NER hits (paper’s compliance example).

**Delegation vs decomposition** — our post-order `_try_post_order_item_edit` is deterministic delegation with engine accountability; LLM path remains decomposition without verification contract.

**Interface paradox** (paper §8): WhatsApp chat UI is L1 messenger metaphor; CE maturity wants visible state (cart, phase, what agent “sees”). Manager dashboard + deterministic customer messages partially compensate.

**Economics** (paper §10): naive context → super-linear/quadratic cost per agent step; compression + caching + selective loading → **5–10×** reduction (Manus, 2025). E-03/E-08 directly affect unit economics.

**Enterprise governance gap** (paper §11): Deloitte 2026 — ~75% plan agentic AI in 2 years, only ~21% mature agent governance; KPMG — deployment 11%→42%→26% (2025). Principal deficit = **quality of world assembled for agent**, not model IQ.

**Romantic ceiling** (paper §14): elegant prompts without encoded intent → linguistically polished, strategically blind (Klarna). E-23 breaks this ceiling.

**Specification debt** (paper §15): TELUS Fuel iX — 21k+ employee-built copilots; without SE, behavior diverges at scale. Our `docs/superpowers/specs/` + E-24 are the antidote.

**This platform = Level 3 enterprise agent** (paper §4): we own orchestrator (`engine.py`), tools (`take_action`), memory (`messages` + `conv.state`), and policies (spec + OKF).

**LangChain four operations** (paper §8):

| Operation | Our stack |
|-----------|-----------|
| **Write** | `record_message`, `_record_cart_observation`, `record_audit` |
| **Select** | `_build_history`, `_okf_grounding`, phase context |
| **Compress** | R-079 merge; kitchen tier-1; *gap: no thread summary* |
| **Isolate** | Per-phase prompts; tenant `restaurant_id` |

**Five context quality criteria** (paper §9):

| Criterion | Target | Current |
|-----------|--------|---------|
| **Relevance** | Min tokens for this step | ⚠ full menu on every order turn |
| **Sufficiency** | No guesswork | ✓ cart, fees, OKF |
| **Isolation** | Role-scoped visibility | ✓ phases; kitchen tier-2 isolated |
| **Economy** | Cache/compress | ⚠ E-01, E-03, E-08 |
| **Provenance** | Source per fragment | ⚠ audit exists; not in LLM prompt |

**Context rot modes** (Breunig, paper §9):

| Mode | Risk here |
|------|-----------|
| **Poisoning** | Stale assistant text vs DB cart |
| **Distraction** | Long post-order history |
| **Confusion** | Menu dump + irrelevant buttons |
| **Clash** | History cart vs `CURRENT CART` authority |

**Klarna lesson (paper §12):** Context without **intent** → optimizes wrong metric (cost vs loyalty). Encode restaurant trade-offs explicitly (E-23).

**Pyramid maturity model** (paper §17):

```
L4 Specification Engineering  → docs/superpowers/specs/*.md
L3 Intent Engineering         → SLA, COD, warmth vs efficiency
L2 Context Engineering        → engine pipeline, OKF, history
L1 Prompt Engineering         → deepseek.py blocks, action_schema
```

**Memory types** (paper §16): working (window), episodic (`messages`), semantic (OKF/menu), procedural (FSM + prompts).

**Enhancement hooks:** E-21–E-24 — see backlog.

---

## Master prompt template

Structured template for authoring or refactoring any LLM prompt in this project. Aligns with White et al. **fundamental contextual statements**, PromptPilot **structure/specificity/language** checks, and Vishnyakova **L1 Pyramid** layer.

### Core components

| Section | Purpose |
|---------|---------|
| **ROLE & Persona** | Exact identity, expertise, voice (“we/our”, restaurant host) |
| **CONTEXT & Background** | Project, audience (WhatsApp customer), business constraints (COD, SLA) |
| **TASK Objective** | One actionable sentence for this phase/call |
| **INPUT Data** | Placeholders filled at runtime: `{menu_text}`, `{cart_summary}`, `{grounding}` |
| **Detailed Instructions** | Sequential steps (decision order, address sequence) |
| **CONSTRAINTS & Boundaries** | Never invent; never list menu in reply; phase-allowed actions only |
| **STYLE & Tone** | Short WhatsApp; multilingual; no em dashes |
| **OUTPUT Format** | `take_action` JSON tool; or JSON-only for extract/segment/forecast |
| **Examples (Few-shot)** | 1–3 canonical input→action pairs; diverse, not exhaustive edge cases |

### Visual structure (authoring format)

Use explicit tags when editing prompts in `conversation_prompts.py` (proposed E-12):

```markdown
[ROLE]
You are the friendly owner and host of {restaurant_name}, taking orders over WhatsApp.

[CONTEXT]
COD only. Delivery ~40 min. Max {max_radius_km} km. Customer speaks any language.

[TASK]
Infer exactly one structured action from the customer's latest message in phase: {dialogue_phase}.

[INPUT — authoritative]
CURRENT CART: {cart_summary}
MENU: {menu_text}
DELIVERY FEES: {delivery_info}
GROUNDED KNOWLEDGE: {grounding}

[INSTRUCTIONS]
Follow DECISION ORDER in the ordering phase. Always call take_action once.

[CONSTRAINTS]
NEVER invent dishes, prices, areas, or hours. NEVER put prices in dish descriptions.
Reply field is tone-only; engine renders authoritative customer text.

[TONE]
Warm, hospitable, WhatsApp-short for cart ops; fuller answers for real food questions.

[OUTPUT FORMAT]
take_action tool: { action, dish_query?, add_qty?, new_total?, items?, reply? }

[EXAMPLES]
"1 mutton biryani" → cart_add dish_query="mutton biryani" add_qty=1
"that's all" (cart non-empty) → checkout_proceed
```

### Mapping: master template → current DeepSeek blocks

| Master section | Current location |
|----------------|------------------|
| ROLE | `_IDENTITY` opening paragraphs |
| CONTEXT | `_IDENTITY` COD/SLA + phase line |
| TASK | Each `_*_BLOCK` “PHASE: …” + “YOUR JOB” |
| INPUT | `_build_context()` keys + `{menu_text}` in blocks |
| INSTRUCTIONS | DECISION ORDER, address steps 1–6 |
| CONSTRAINTS | `#1 RULE`, NEVER INVENT, phase action lists |
| TONE | LANGUAGE + TONE in `_IDENTITY` |
| OUTPUT | `_DS_TOOL` / `action_schema.py` |
| EXAMPLES | Parsing examples in `_ORDERING_BLOCK` |

---

## What we already do well

These patterns already align with Anthropic’s guidance:

| Practice | Where |
|----------|--------|
| Phase-specific system blocks (smaller, focused prompts per FSM phase) | `deepseek.py` `_ORDERING_BLOCK`, `_ADDRESS_BLOCK`, `_CONFIRMATION_BLOCK`, `_POST_ORDER_BLOCK` |
| Authoritative state **outside** chat history | `_build_context()` → `cart_summary`, `cart_lines`; prompt text: “CURRENT CART (authoritative)” |
| Cart observation in history after mutations | `_record_cart_observation()` → `[Cart updated] …` in DB history |
| Hybrid just-in-time grounding | `okf/retrieval.py` — entity pins (language-agnostic) + lexical `pg_trgm` bonus |
| Grounding appended last (overrides model priors) | `DeepSeekConversationAgent._build_system()` suffix |
| Single structured tool (`take_action`) | `action_schema.py` — one action per turn, validated before engine dispatch |
| History window + merge same-role turns | `_build_history()` — `conversation_history_limit`, R-079 merge |
| Deterministic engine paths before LLM | Category queries, off-topic guard, catalog cart-edit, post-order line edits |
| Kitchen tier-1 deterministic + tier-2 LLM supplement | `kitchen_summary.py` — authoritative block first, net-new lines only |
| KG-style grounding (training-free) | OKF retrieve + `grounding_block()` — aligns with Li et al. KG-collaboration paper |
| Prompt patterns (persona, recipe, constraints) | `_IDENTITY`, phase blocks — aligns with White et al. pattern catalog |
| Dish arbiter (limited multi-candidate reasoning) | `DeepSeekArbiter` / `ClaudeArbiter` — partial ToT analogue |
| LangChain write/select/compress/isolate | Engine history + OKF + cart observations (compress partial) |
| L4 specification corpus | `docs/superpowers/specs/` business rules (Vishnyakova SE layer) |
| Prompt patterns (Persona, Recipe, Template, Context Manager) | White et al. catalog — informal adoption |

---

## Enhancement backlog

Prioritized opportunities to improve context efficiency and agent reliability.

### P0 — High impact, fits current architecture

#### E-01: Tighten history window by phase

**Problem:** Long WhatsApp threads inflate context; post-order acks and status pings add noise unrelated to the current decision.

**Anthropic fit:** Compaction / high-signal history only.

**Proposal:**

- `ordering` / `address_capture`: keep last N messages (current `conversation_history_limit`).
- `post_order`: shorter window (e.g. last assistant message + last 3–5 turns) since `_POST_ORDER_BLOCK` already encodes order status.
- Optionally **exclude** `cart_observation` rows older than the latest observation.

**Touch:** `engine.py` `_build_history()`, `config.py` (per-phase limits).

**Tests:** `tests/conversation/test_ok_post_order.py`, history regression suite.

---

#### E-02: Reduce system prompt duplication (DeepSeek vs Claude)

**Problem:** Two divergent conversation prompts (`deepseek.py` phase blocks vs `claude.py` `_CONVERSATION_SYSTEM`) increase maintenance cost and parity bugs.

**Anthropic fit:** Minimal sufficient system information; single source of truth.

**Proposal:**

- Extract shared sections (`IDENTITY`, cart authority, never-invent, delivery fees) into `src/app/llm/conversation_prompts.py`.
- DeepSeek keeps phase blocks; Claude composes from the same constants + `_phase_guidance()`.

**Touch:** `deepseek.py`, `claude.py`, new `conversation_prompts.py`.

**Tests:** Existing `tests/llm/test_*` prompt assertions.

---

#### E-03: Token-efficient menu in context

**Problem:** Full `menu_text` in every ordering-turn system prompt is high token cost; drives context rot on large menus.

**Anthropic fit:** Just-in-time retrieval; smallest high-signal set.

**Proposal (hybrid):**

- **Always inject:** cart summary, fees, hours, restaurant location (already grounded).
- **On demand:** inject menu slice only when intent is `menu_show`, category query, or dish-named add (engine already has category handler).
- **OKF:** menu/policy docs already pinned via `retrieve()` — lean on OKF for availability questions instead of full menu dump.

**Touch:** `engine.py` `_build_context()`, `_ORDERING_BLOCK` (teach model that menu may be partial + use `menu_show`).

---

#### E-04: Tool result / reply field discipline

**Problem:** `_DS_TOOL` / `take_action` `reply` field can tempt the model to author prices, menus, or order numbers — duplicated with engine rendering.

**Anthropic fit:** Tools return token-efficient, authoritative data; agent behavior follows tool contract.

**Proposal:**

- Strengthen `reply` description in `action_schema.py`: “tone-only; max 1 short sentence; never list dishes or prices.”
- Engine already renders authoritative text — document that `reply` is optional hint only (already partially stated).

**Touch:** `action_schema.py`, `_IDENTITY` / `_ORDERING_BLOCK` one-liner.

---

### P1 — Medium impact

#### E-05: Structured conversation memory (external notes)

**Problem:** Multi-session customers and long modify flows lose nuance when history is windowed.

**Anthropic fit:** Structured note-taking / agentic memory outside the window.

**Proposal:**

- Persist compact `conv.state["agent_notes"]` (e.g. last confirmed order #, pending modify intent, resale offer id).
- Inject a 2–3 line `## Session notes` block into system prompt from state — not full history.

**Touch:** `engine.py` `_build_context()`, state schema docs.

---

#### E-06: History metadata for grounding (direction + source)

**Problem:** Spec notes raw `{role, content}` history lacks `source` (catalog vs text vs LLM) — model may trust stale assistant prose over DB cart.

**Anthropic fit:** Metadata as relevance signals (like file paths in Claude Code).

**Proposal:**

- Extend `_render_history_content()` prefixes: `[catalog]`, `[system]`, `[customer]`.
- Skip mirroring full button bodies when `msg_type=cart_observation` already present.

**Touch:** `engine.py` `_render_history_content()`, `_build_history()`.

---

#### E-07: Router + completion prompt consolidation

**Problem:** Three small LLM calls possible per turn (router, completion, agent) — each spends attention budget.

**Anthropic fit:** Minimal tool set; avoid redundant inference.

**Proposal:**

- Audit call graph in `handle_inbound` → `_handle_customer_ai`.
- Where deterministic guards already classify intent, skip router LLM (already partially done).
- Consider folding completion detection into main agent when cart non-empty (agent already has `checkout_proceed`).

**Touch:** `engine.py`, `deepseek.py` `DeepSeekRouterClassifier` / `DeepSeekCompletionDetector`.

---

#### E-08: OKF retrieval budget cap

**Problem:** `grounding_block()` can grow with many pinned docs + lexical hits.

**Anthropic fit:** Smallest high-signal token set.

**Proposal:**

- Hard cap: max 4 docs or ~800 tokens rendered grounding.
- Priority order: policy → order → customer → dish → lexical matches.
- Truncate `body` with “…” for long markdown sections.

**Touch:** `okf/retrieval.py`, `grounding_block()`.

---

### P2 — Longer horizon / platform

#### E-09: Conversation compaction for returning customers

**Anthropic fit:** Compaction when approaching window limits.

**Proposal:** When `Message` count > threshold, summarize older turns into one `system_summary` message row (kitchen-style: preserve order #, cart state, address progress; drop redundant menu sends).

**Touch:** New `conversation/compaction.py`, Celery or inline on `_build_history`.

---

#### E-10: Sub-agent for complex modify / complaint flows

**Anthropic fit:** Sub-agent returns 1–2k token distilled summary to lead agent.

**Proposal:** Post-delivery complaint or multi-line modify spawns a focused sub-call with order + ticket context only; main agent gets structured `{issue, suggested_action}` JSON.

**Touch:** New port in `llm/port.py`, `engine.py` complaint branch.

---

#### E-11: Anthropic context management platform features

**Reference:** [Claude context management](https://www.anthropic.com/news/context-management) — tool result clearing, memory tool (file-based notes).

**Proposal:** When on Claude provider, enable platform tool-result clearing for multi-step internal tools (if we add MCP / multi-tool loops later).

---

### P1 — Research-driven (papers + master template)

#### E-12: Refactor prompts to master prompt sections

**Source:** Master prompt template + [Prompt Pattern Catalog](https://arxiv.org/abs/2302.11382) + Anthropic sectioned prompts.

**Proposal:**

- Create `src/app/llm/conversation_prompts.py` with tagged sections: `[ROLE]`, `[CONTEXT]`, `[TASK]`, `[INPUT]`, `[INSTRUCTIONS]`, `[CONSTRAINTS]`, `[TONE]`, `[OUTPUT]`, `[EXAMPLES]`.
- `_build_system()` assembles sections; phase blocks supply `[TASK]` + phase-specific `[INSTRUCTIONS]`.
- Enables E-02 (SSOT) and makes diffs reviewable.

**Touch:** `deepseek.py`, `claude.py`, new `conversation_prompts.py`.

---

#### E-17: ToT-lite for ambiguous dish / multi-intent messages

**Source:** [Tree of Thoughts](https://arxiv.org/abs/2305.10601).

**Proposal:** When arbiter returns low confidence or router returns `unknown`:

1. Internal “thought” step (hidden): generate 2–3 candidate interpretations (add vs question vs checkout).
2. Score against cart state + phase (deterministic rubric or tiny LLM call).
3. Execute winning branch or ask one clarifying question.

**Touch:** `engine.py` pre-LLM branch; optional `llm/port.py` `ThoughtEvaluator` port.

**Note:** Default path stays single-shot for latency; ToT only on ambiguity.

---

#### E-18: Internal prompt pattern catalog

**Source:** [Prompt Pattern Catalog](https://arxiv.org/abs/2302.11382).

**Proposal:** Add `docs/prompt-patterns.md` documenting which patterns apply per prompt type:

- Conversation agent → Persona + Recipe + Constraint + Tool contract
- Kitchen tier-2 → Persona + Output format (NONE or lines)
- Marketing copywriter → Persona + Template + JSON output
- Segment compiler → Meta-language (DSL) + JSON-only

Prevents ad-hoc prompt edits that break pattern composition.

---

#### E-19: PromptPilot-style dev review loop

**Source:** [PromptPilot](https://arxiv.org/abs/2510.00555).

**Proposal:** Script `scripts/review_prompt_regression.py` (mirror PromptPilot DO1–DO4):

- **DO1:** Flag error domain — missing audience (WhatsApp customer), purpose (phase task), structure, specificity, language.
- **DO2:** Guided questions before suggesting edits (“What phase actions are allowed?”, “What is authoritative cart source?”).
- **DO3:** Change summary + “prompt parity tests must pass” as completion signal.
- **DO4:** Human merges; never auto-edit production prompts.

Input: failing test name or transcript JSON + current `_ORDERING_BLOCK` / `_POST_ORDER_BLOCK`. Output: markdown review.

**Touch:** New script; optional CI on `tests/conversation/` failures.

---

#### E-20: OKF subgraph citations in prompt

**Source:** [KG-integrated collaboration](https://arxiv.org/abs/2402.04978).

**Proposal:** Extend `grounding_block()` to prefix each fact with retrievable id:

```
[okf:policy:delivery] Delivery fees: ≤3 km free …
[okf:dish:42] Chicken Biryani — AED 22 …
```

Instruct model: “Cite only `[okf:…]` facts for factual claims; if no okf tag applies, defer to team phone.”

Improves transparency and reduces hallucination on long-tail Q&A.

**Touch:** `okf/retrieval.py`, `_IDENTITY` one paragraph, tests in `test_location_grounding.py`.

---

#### E-21: Question Refinement for vague inbound (Pattern Catalog)

**Source:** White et al. **Question Refinement** pattern — “suggest a better version of the question within scope X.”

**Proposal:** When router returns `unknown` and message is short/vague (“that one”, “same as last time”), one lightweight LLM call or template asks a single clarifying question scoped to phase (ordering vs post_order) before main agent runs.

**Touch:** `engine.py` pre-`_handle_customer_ai` branch.

---

#### E-22: Context rot guards (Breunig / Vishnyakova)

**Source:** Poisoning, distraction, confusion, clash taxonomy.

**Proposal:**

- **Poisoning/clash:** Strip assistant messages that duplicate cart state when `cart_observation` exists for same turn window.
- **Distraction:** E-01 phase windows (especially post_order).
- **Confusion:** E-03 JIT menu; drop verbose button option lists from history when body already sent.
- Add metric: log context token estimate per turn for ops dashboard.

**Touch:** `_build_history()`, `_render_history_content()`, observability.

---

#### E-23: Intent engineering block in system prompt (Pyramid L3)

**Source:** Vishnyakova §14 — IE encodes trade-off hierarchy; “context without intent is noise” (Huryn, 2026).

**Proposal:** Add compact `[INTENT]` section to conversation prompts:

- Primary: complete accurate orders from menu; 40-min SLA promise; warm brand voice.
- Secondary: batch when possible; minimize unnecessary messages.
- Never optimize: silent errors, invented dishes/prices, rude brush-offs.
- Escalate to human phone for: complaints, refunds, catering, facts not in OKF.

Distinct from constraints — this is **what to optimize for** when rules conflict.

**Touch:** `conversation_prompts.py` / `_IDENTITY`; mirror in spec doc.

---

#### E-24: Specification engineering traceability (Pyramid L4)

**Source:** Vishnyakova §15 — SE as machine-readable constitution; specs are laws, context is enforcement.

**Proposal:** Link each prompt rule to spec section ID in comments (e.g. `R-072 cart authority → spec §ordering`). CI check: grep `_ORDERING_BLOCK` for rules without spec reference when adding new NEVER/ALWAYS lines.

**Touch:** `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md`, prompt files, optional `scripts/lint_prompt_spec_refs.py`.

---

## Phase prompt altitude review

Anthropic warns against **brittle if/else prompts** and **overly vague** prompts. Current phase blocks are detailed; periodic review should ask:

| Question | Action if “no” |
|----------|----------------|
| Can the engine handle this deterministically instead? | Move rule to `engine.py`; shorten prompt |
| Is this rule duplicated in engine + prompt? | Delete from prompt |
| Did we add this rule without a failing test? | Remove or add regression test |
| Does the model still need this example after fine-tuning / model upgrade? | Prune examples |

**Candidates for engine-side migration (shorter prompts):**

- Menu show → already `menu_show` action + engine send
- Full cart authority → already `cart_summary` + observations
- Address sequence steps → partially deterministic in engine FSM

---

## Implementation checklist (per enhancement)

1. Query graph: `/graphify query "<enhancement area>"` before edits.
2. Failing test first (TDD).
3. Update [prompt-inventory.md](./prompt-inventory.md) if symbols move.
4. Run prompt tests: `tests/llm/test_deepseek_prompt.py`, `test_location_grounding.py`, `test_address_guardrails.py`, `test_cart_state_prompt_precedence.py`.
5. Run conversation regressions: `tests/conversation/test_ok_post_order.py`, `test_engine_ordering.py`.
6. `graphify . --update` after code changes.
7. Log bullet in `understanding.txt`.

---

## Recommended sequence

```
E-04 (reply discipline)      → quick, low risk
E-22 (context rot guards)    → pairs with E-01; addresses Vishnyakova/Breunig modes
E-01 (phase history window)  → post-order "Ok" / distraction rot
E-23 (intent block)          → Klarna-style strategic blind spot prevention
E-08 (OKF cap)               → economy criterion; pairs with E-20
E-12 + E-02 (master + SSOT)  → White/PromptPilot structure before growth
E-03 (menu JIT)              → relevance + economy win
E-20 (OKF cites)             → provenance + KG paper
E-19 (PromptPilot review)    → dev loop (DO1–DO4)
E-21, E-17, E-24, E-05–E-11  → scale / governance
```

---

## Further reading

### Industry (Anthropic)

- [Prompt engineering overview](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview)
- [Building effective AI agents](https://www.anthropic.com/research/building-effective-agents)
- [Writing tools for AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents)
- [Multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)
- [Memory and context management cookbook](https://platform.claude.com/cookbook/tool-use-memory-cookbook)
- [Context rot (Chroma)](https://research.trychroma.com/context-rot)

### Academic (arXiv + PDFs)

- [Context Engineering: Corporate Multi-Agent Architecture](https://arxiv.org/abs/2603.09619) — Vishnyakova, 2026 (`2603.09619v2.pdf`)
- [Prompt Pattern Catalog](https://arxiv.org/abs/2302.11382) — White et al. (`2302.11382v1.pdf`)
- [PromptPilot](https://arxiv.org/abs/2510.00555) — Gutheil et al., ICIS 2025 (`2510.00555v1.pdf`) · [GitHub](https://github.com/FraunhoferFITBusinessInformationSystems/PromptPilot)
- [Tree of Thoughts](https://arxiv.org/abs/2305.10601) — Yao et al., NeurIPS 2023
- [KG-integrated LLM reasoning](https://arxiv.org/abs/2402.04978) — Li et al.

### Guides & surveys

- [Prompt Engineering Guide — papers](https://www.promptingguide.ai/papers)
- [LangChain — context engineering for agents](https://blog.langchain.com/context-engineering-for-agents/) (write/select/compress/isolate)
- [Breunig — how contexts fail](https://www.dbreunig.com/2025/06/22/how-contexts-fail-and-how-to-fix-them.html) (context rot taxonomy)
- [Advanced prompt engineering (Mercity)](https://www.mercity.ai/blog-post/advanced-prompt-engineering-techniques/)
- [ACM — prompt patterns in the wild](https://dl.acm.org/doi/10.5555/3721041.3721046)