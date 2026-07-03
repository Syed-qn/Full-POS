# Marketing Studio — Full Design (Living Document)

**Status:** Draft — brainstorming approved (Section 1: phasing + architecture)  
**Created:** 2026-07-02  
**Last updated:** 2026-07-03 (Phase 5 expanded)  
**Owner:** Manager dashboard / `marketing` bounded context  
**Spec truth:** `docs/superpowers/specs/2026-06-06-whatsapp-restaurant-platform-design.md` §4.7  
**Design brief:** `docs/design/dashboard-design-brief.md` — Screen 5: Marketing Studio  
**Implementation plan:** TBD — invoke `writing-plans` after spec review gate  

> **Living doc:** This file is the single dump for phased plan, API contracts, UI specs, and open questions. Update `Last updated` and the **Changelog** at the bottom on every edit. Do **not** treat this as frozen until the user approves the written spec and we invoke `writing-plans`.

---

## 1. Goal

Deliver the full **Klaviyo-style Marketing Studio** on the manager dashboard:

| Goal | Manager outcome |
|------|-----------------|
| **Prove ROI** | See campaign history, delivery, and conversion on Marketing (not only Reports aggregate) |
| **Target better** | Build custom segments in plain English; send to RFM or saved segment; optional coupon |
| **Less friction** | Auto-poll Meta approval, rejection fix-and-resubmit, ephemeral Today's Special lifecycle |
| **Drive repeat orders** | Automation tab: welcome, win-back, reorder reminders, recurring promos |

**Phase 5 adds:** AI header image generation, scheduled broadcast UI.  
**Non-goals (post–Phase 5):** Video headers, A/B campaigns, custom automation DSL (4b).

---

## 2. Architecture decision (approved)

**Approach 3 — Incremental delivery on current tab layout → migrate to nested routes later.**

- Ship four delivery phases using the existing `MarketingScreen` tab bar; add tabs as features land.
- Refactor to nested routes (`/marketing/broadcast`, `/segments`, …) only if the screen exceeds ~1500 lines (expected end of Phase 3).
- **Rejected for now:** big-bang nested routes (Approach 2); single monolith forever (Approach 1).

### Tab evolution

```
Today:     WhatsApp | Today's Special | Automation (Soon)
Phase 1:   WhatsApp | Today's Special | Campaigns | Automation (Soon)
Phase 2:   WhatsApp | Today's Special | Segments | Campaigns | Automation (Soon)
Phase 4:   WhatsApp | Today's Special | Segments | Campaigns | Automation
```

### Cross-cutting rules (unchanged)

- STOP / opt-out footer on every template (`Reply STOP to opt out`).
- UAE marketing window **09:00–18:00** Asia/Dubai; suppress outside window.
- Per-customer cap **2 marketing messages / rolling 24h**; suppress over cap.
- Only **approved** templates can broadcast or power Today's Special when enabled.
- `record_audit` on segment/automation/campaign/template state changes (same transaction).
- Money: AED `Decimal`; DB timestamps UTC; Celery/schedulers Asia/Dubai.
- Tests: TDD; no real Meta/Anthropic in tests (ports faked).

---

## 3. Current state inventory (2026-07-02)

### 3.1 Frontend — `MarketingScreen.tsx`

| Area | Status |
|------|--------|
| WhatsApp broadcast | Live — RFM pills, template pills, two-tap send, live preview |
| Today's Special | Live — None / Until today / Custom time; lead minutes; save to settings |
| Create template modal | Live — AI draft, image upload, optional URL button, submit to Meta |
| Automation tab | Placeholder only |
| Campaign history | **Missing** — APIs exist, UI on Reports only |
| Custom segments | **Missing** — backend DSL + LLM compiler exist |
| Coupon on broadcast | **Missing** — `coupon_value` in API, not in UI |
| Generate image/video | Disabled "Soon" badges |

### 3.2 Frontend API client — `marketingApi.ts`

| Function | Used on Marketing page |
|----------|------------------------|
| `fetchTemplates`, `fetchAudience`, `draftTemplate`, `uploadTemplateImage`, `createTemplate`, `submitTemplate`, `refreshTemplate`, `deleteTemplate`, `broadcast` | Yes |
| `fetchCampaigns`, `getCampaignStats` | No — **AnalyticsScreen** only |
| `fetchSegments` | No — no segment UI |

### 3.3 Backend — `src/app/marketing/`

| Component | Status |
|-----------|--------|
| Models: `WaTemplate`, `Campaign`, `Segment`, `MarketingSend`, `OptOut`, `MarketingMedia` | Live |
| Models: `automations`, `recurring_message_state` | **Not migrated** (spec §3) |
| Router: templates, audience, broadcast, campaigns list/stats, segments CRUD, tick | Live |
| Router: `POST /segments/compile`, `POST /segments/preview` | **Missing** |
| `segments.py` DSL validate/compile/evaluate | Live |
| `rfm.py` named buckets | Live |
| `SegmentCompiler` LLM port (`llm/`) | Live |
| `worker.py`: `poll_template_statuses`, `cleanup_ephemeral_templates`, `send_scheduled_campaigns` | Live (verify beat schedule) |
| `campaign_stats` / `campaign_stats_bulk` | Live |
| `template_meta.py` resumable image upload | Verify / harden (GAP_LIST) |

### 3.4 RFM audience keys (live)

`champions`, `loyal`, `potential`, `at_risk`, `lost`, `new`, `all` — mutually exclusive buckets; `all` = entire customer base.

### 3.5 Campaign types (DB)

`todays_special` | `recurring` | `automation` | `promotional` (broadcast uses `promotional`).

---

## 4. Phased delivery plan

### Phase 1 — Prove ROI (Campaigns tab)

**Priority:** First implementation slice (approved).

#### 4.1.1 User stories

1. As a manager, I see every past marketing send in one table on Marketing.
2. As a manager, I see sent / delivered / converted and conversion % per campaign.
3. As a manager, I open a campaign row and see suppression breakdown (opt-out, cap, window).
4. As a manager, Reports still shows aggregate KPIs; Marketing owns detail.

#### 4.1.2 UI — Campaigns tab

**Layout:** Full-width card below tab bar (no split preview — table-first).

```
┌─────────────────────────────────────────────────────────────────┐
│ SUMMARY STRIP                                                    │
│ [Campaigns: N] [Messages sent: X] [Orders: Y] [Conv rate: Z%] │
├─────────────────────────────────────────────────────────────────┤
│ CAMPAIGN TABLE (sort: newest first)                              │
│ Date | Template | Audience | Type | Status | Sent | Del | Conv │
│ ... clickable row → detail drawer                                │
└─────────────────────────────────────────────────────────────────┘
```

**Summary strip:** Same four metrics as Reports `Marketing Messages` card, computed client-side from `fetchCampaigns()` (reuse logic from `AnalyticsScreen`).

**Table columns:**

| Column | Source |
|--------|--------|
| Date | `Campaign.created_at` (new field on API) or `scheduled_at` fallback |
| Template | `template_name` (new enriched field) |
| Audience | `audience_label` (new enriched field) |
| Type | `type` — humanise: `promotional` → "Broadcast", `todays_special` → "Today's Special" |
| Status | `status` |
| Sent | `stats.sent` |
| Delivered | `stats.delivered` |
| Converted | `stats.converted` |

**Detail drawer (slide-over):**

- Fetches `GET /campaigns/{id}/stats` on open (full status histogram).
- Shows: `queued`, `sent`, `delivered`, `read`, `replied` (if tracked), `converted`, `conversion_rate`.
- Suppression section: `suppressed_optout`, `suppressed_cap`, `suppressed_window` from stored `Campaign.stats` merged with ledger.
- Template preview thumbnail (body snippet + image if header present) — read-only.

**Empty state:** Mirror Reports — "No campaigns yet" + link hint to WhatsApp tab.

**Polling:** `usePoll(fetchCampaigns, 60_000)` while tab active (match Reports).

#### 4.1.3 API changes

**Extend `CampaignResponse` schema:**

```python
class CampaignResponse(BaseModel):
    id: int
    type: str
    status: str
    stats: dict[str, Any]
    created_at: datetime          # NEW
    template_name: str | None     # NEW — join WaTemplate.meta_template_name
    audience_label: str | None    # NEW — see resolution below
    segment_id: int | None        # NEW — expose for debugging/advanced
    template_id: int | None       # NEW
```

**Audience label resolution** (service helper, tenant-scoped):

1. If `campaign.segment_id` → segment `name`
2. Else if stats JSON contains `rfm_segment` key (store on broadcast) → RFM label from `RFM_SEGMENTS`
3. Else → `"All Customers"`

**Broadcast enhancement (small):** Persist `rfm_segment` in `Campaign.stats` at create time so historical rows are labelable:

```python
# in broadcast_now after create_campaign
camp.stats = {**(camp.stats or {}), "rfm_segment": body.rfm_segment or "all"}
```

**No new endpoints** for Phase 1 — enrich existing `GET /campaigns` and use existing `GET /campaigns/{id}/stats`.

#### 4.1.4 Frontend files

| File | Change |
|------|--------|
| `frontend/src/lib/marketingApi.ts` | Extend `CampaignResponse` type; export `fetchCampaigns`, `getCampaignStats` (already exist) |
| `frontend/src/screens/MarketingScreen.tsx` | Add `campaigns` tab; summary + table + drawer |
| `frontend/src/screens/MarketingScreen.module.css` | Table, drawer, summary strip styles |
| `frontend/src/screens/MarketingScreen.campaigns.test.tsx` | **NEW** — empty state, row render, drawer stats |

**Optional:** Extract `CampaignSummaryStrip` shared with `AnalyticsScreen` to DRY metrics (Phase 1b polish).

#### 4.1.5 Backend files

| File | Change |
|------|--------|
| `src/app/marketing/schemas.py` | Extend `CampaignResponse` |
| `src/app/marketing/router.py` | Enrich `list_campaigns` with joins + labels |
| `src/app/marketing/service.py` | `audience_label_for_campaign(campaign, segment?)` helper |
| `src/app/marketing/router.py` `broadcast_now` | Store `rfm_segment` in stats |
| `tests/marketing/test_router.py` | Enriched list fields; broadcast stats persistence |

#### 4.1.6 Tests (Phase 1 exit criteria)

- [ ] `test_list_campaigns_includes_template_and_audience_labels`
- [ ] `test_broadcast_persists_rfm_segment_in_stats`
- [ ] `test_campaign_stats_returns_suppression_counts`
- [ ] Frontend: campaigns tab renders skeleton → table → drawer
- [ ] `ruff check` + `pytest tests/marketing/` green
- [ ] Graphify update on changed files

---

### Phase 2 — Target better (Segments tab + broadcast upgrades)

**Depends on:** Phase 1 optional (Campaigns tab can ship in parallel; no hard dependency).  
**Priority:** Second implementation slice.

#### 4.2.1 User stories

1. As a manager, I describe an audience in plain English, compile it, see how many customers match, and save it as a reusable segment.
2. As a manager, I see all saved segments with live counts and can delete ones I no longer need.
3. As a manager, when broadcasting I choose **either** an RFM bucket **or** a saved custom segment (never both).
4. As a manager, I optionally attach an AED coupon to a broadcast so opted-in customers receive a unique code in the template message.
5. As a manager, I understand when a coupon cannot be issued (customer has no prior order) without the send failing.

#### 4.2.2 Segment DSL reference (manager-facing)

Compiled segments use the validated DSL in `src/app/marketing/segments.py`. Managers never edit JSON directly unless they expand the technical preview.

| Field | Meaning | Example plain English |
|-------|---------|----------------------|
| `total_spend` | Lifetime AED spend | "spent over 200" |
| `order_count` | Lifetime order count | "ordered 3 or more times" |
| `last_order_days_ago` | Recency (days) | "ordered in the last 30 days" |
| `tag` | Customer tag key | "VIP customers" |
| `ordered_dish_id` | Dish ID + optional `min_count` | "ordered biryani 3+ times" (requires dish catalog in compile prompt — see §4.2.8) |

Root combinator: `all` (AND) or `any` (OR). Security: `validate_dsl` allowlist runs before any SQL is built.

#### 4.2.3 UI — Segments tab

**Layout:** Single-column builder on top, saved segments table below (no live preview — segments are audience definitions, not messages).

```
┌─────────────────────────────────────────────────────────────────┐
│ BUILD A SEGMENT                                                  │
│ Try an example: [Spent 200+] [Last 30 days] [VIP] [3+ orders]  │
│                                                                  │
│ Plain English                                                    │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ customers who spent over AED 200 in the last 60 days       │ │
│ └─────────────────────────────────────────────────────────────┘ │
│ [✨ Compile segment]                                             │
│                                                                  │
│ ✓ 47 customers match                    [▸ View compiled rules] │
│   (expandable <pre> JSON DSL, monospace, collapsed by default)  │
│                                                                  │
│ Segment name                                                     │
│ [ High spenders · last 60 days        ]                          │
│ [💾 Save segment]                                                │
├─────────────────────────────────────────────────────────────────┤
│ SAVED SEGMENTS                                                   │
│ Name          | Customers | Updated      | Actions               │
│ VIP regulars  | 12        | 2 Jul, 14:30   | [Delete]              │
│ Biryani fans  | 47        | 1 Jul, 09:15   | [Delete]              │
└─────────────────────────────────────────────────────────────────┘
```

**States:**

| State | UI |
|-------|-----|
| Idle | Textarea empty; Compile disabled until ≥10 chars |
| Compiling | Button shows "Compiling…"; textarea disabled |
| Preview ready | Green count badge; Save enabled when name ≥3 chars |
| Compile error | Red inline message from API `detail` |
| Saving | Save button busy |
| Empty saved list | "No saved segments yet — build one above." |

**Example chips** (click → fill textarea, do not auto-compile):

- `customers who spent over AED 200`
- `customers who ordered in the last 30 days`
- `VIP customers`
- `customers who ordered 3 or more times`
- `customers who spent over AED 100 and ordered in the last 14 days`

**Delete:** `ConfirmDialog` — "Delete segment «{name}»? Past campaigns that used it keep their history."

**Reload:** `fetchSegments()` on tab mount and after save/delete.

#### 4.2.4 UI — WhatsApp tab upgrades

**Audience section** — two labelled groups in one card:

```
SELECT AUDIENCE
Choose one group. RFM buckets and saved segments cannot be combined.

RFM (behaviour buckets)          ← existing pills + counts
[Champions 12] [Loyal 34] … [All Customers 210]

Saved segments                   ← NEW; hidden row when list empty
[Biryani fans 47] [VIP regulars 12]
```

**Selection state machine (frontend):**

```typescript
type AudienceSelection =
  | { mode: "rfm"; key: string }           // default { mode: "rfm", key: "all" }
  | { mode: "segment"; segmentId: number };
```

- Clicking an RFM pill → `{ mode: "rfm", key }` — clears segment highlight.
- Clicking a saved segment pill → `{ mode: "segment", segmentId }` — clears RFM highlight.
- Default on load: `{ mode: "rfm", key: "all" }` (unchanged behaviour for existing users).

**Coupon row** (new, above Send bar):

```
Optional coupon (AED)   [  10.00  ]   ℹ️ Unique code per customer; needs a prior order
```

- Input: `type="number"`, `min=0`, `max=500`, `step=0.01`, empty = no coupon.
- Serialized as decimal string `"10.00"` on broadcast.
- Not shown on Today's Special tab (coupons are broadcast-only in Phase 2).

**Send bar label:**

| Selection | Label |
|-----------|-------|
| RFM `all` | `📣 Send via WhatsApp · All Customers` |
| RFM named | `📣 Send via WhatsApp · Champions` |
| Segment | `📣 Send via WhatsApp · Biryani fans (47)` |

**Broadcast payload:**

```typescript
// mode rfm
broadcast({ template_id, type: "promotional", rfm_segment: key, coupon_value?: string })

// mode segment
broadcast({ template_id, type: "promotional", segment_id, coupon_value?: string })
// omit rfm_segment entirely (not "all")
```

#### 4.2.5 API — schemas and endpoints

**New request/response models** (`schemas.py`):

```python
class SegmentCompileRequest(BaseModel):
    plain_english: str = Field(..., min_length=10, max_length=600)

class SegmentCompileResponse(BaseModel):
    dsl: dict[str, Any]
    preview_count: int
    plain_english: str  # echo for save flow

class SegmentPreviewRequest(BaseModel):
    dsl: dict[str, Any]

class SegmentPreviewResponse(BaseModel):
    preview_count: int
```

**Extend `SegmentResponse`:**

```python
class SegmentResponse(BaseModel):
    id: int
    name: str
    last_preview_count: int | None
    plain_english: str | None   # NEW — for edit/display
    updated_at: datetime        # NEW — from TimestampMixin
```

**Endpoints:**

| Method | Path | Status | Body / response |
|--------|------|--------|-----------------|
| `POST` | `/api/v1/marketing/segments/compile` | 200 | `SegmentCompileRequest` → `SegmentCompileResponse` |
| `POST` | `/api/v1/marketing/segments/preview` | 200 | `SegmentPreviewRequest` → `SegmentPreviewResponse` |
| `POST` | `/api/v1/marketing/segments` | 201 | existing `SegmentCreate` |
| `GET` | `/api/v1/marketing/segments` | 200 | `list[SegmentResponse]` |
| `DELETE` | `/api/v1/marketing/segments/{id}` | 204 | — |

**`POST /segments/compile` flow (router → service):**

1. Load active dish catalog for tenant (id + name) via **menu service** — inject into compiler context (§4.2.8).
2. `dsl = get_segment_compiler().compile(plain_english)` — already calls `validate_dsl` in Claude/DeepSeek path; service **re-validates** for all providers.
3. `count = await preview_count(session, restaurant_id=..., dsl=dsl)`.
4. Return `{ dsl, preview_count, plain_english }`.

**Errors:**

| Condition | HTTP | Message |
|-----------|------|---------|
| LLM non-JSON / invalid DSL | 422 | "Could not understand that audience description. Try simplifying." |
| `plain_english` too short | 422 | validation error |
| Compiler timeout / API fault | 502 | "Segment compile failed: …" (logged server-side) |

**`POST /segments/preview`:** `validate_dsl` → `preview_count` — lets UI re-count after manual DSL inspect (future); Phase 2 uses same compile response count.

**`DELETE /segments/{id}`:**

- Service `delete_segment(session, restaurant_id, segment_id)`:
  - 404 if not found / wrong tenant
  - 409 if segment referenced by `campaign.status in ('scheduled','sending')` (optional guard)
  - `record_audit` action `deleted`
  - Hard delete row (campaigns keep `segment_id` FK for history — nullable, no cascade)

**`POST /broadcast` tightening:**

```python
# Mutual exclusivity
if body.segment_id is not None and body.rfm_segment not in (None, "", "all"):
    raise HTTPException(422, "Choose a saved segment or an RFM bucket, not both")

# Audience resolution (unchanged precedence in run_campaign_send):
# segment_id on campaign → evaluate_segment DSL
# OR rfm_segment → segment_customer_ids
# OR all customers

# Persist audience metadata for Phase 1 Campaigns labels:
camp.stats = {
    **(camp.stats or {}),
    "rfm_segment": body.rfm_segment if body.segment_id is None else None,
    "segment_id": body.segment_id,
}
```

**Coupon (`coupon_value`):** already on `BroadcastRequest`. Validate in router:

```python
if body.coupon_value is not None:
    Decimal(body.coupon_value)  # raises → 422 "coupon_value must be a decimal string"
    if Decimal(body.coupon_value) <= 0:
        raise HTTPException(422, "coupon_value must be positive")
```

Backend send behaviour (existing, document for managers):

- Per recipient: if `coupon_value` set AND customer has ≥1 order → `issue_coupon` → code injected in template payload.
- If no prior order → message still sends, **without** coupon code (no error).

#### 4.2.6 Service layer (new functions)

| Function | Module | Responsibility |
|----------|--------|----------------|
| `compile_segment_from_english(session, *, restaurant_id, plain_english)` | `service.py` | Dish catalog fetch, compiler, validate, preview_count |
| `preview_segment(session, *, restaurant_id, dsl)` | `service.py` | validate + preview_count |
| `delete_segment(session, *, restaurant_id, segment_id)` | `service.py` | tenant guard, audit, delete |
| `dish_catalog_for_compiler(session, *, restaurant_id)` | `service.py` | `[{id, name}]` active dishes — calls menu service, not menu models from router |

**Audit events:**

| Action | Entity | `after` payload |
|--------|--------|-----------------|
| `compiled` | `segment` | `{ preview_count }` (optional — only if we audit compile; else compile is read-only) |
| `created` | `segment` | existing |
| `deleted` | `segment` | `{ name }` |

Compile is read-only — **no audit** on compile to avoid noise (decision locked).

#### 4.2.7 Frontend files

| File | Change |
|------|--------|
| `frontend/src/lib/marketingApi.ts` | Add `compileSegment`, `previewSegment`, `createSegment`, `deleteSegment`, `fetchSegments`; extend `SegmentResponse`; extend `broadcast` types |
| `frontend/src/screens/MarketingScreen.tsx` | `segments` tab; WhatsApp audience state machine; coupon input; load segments on mount |
| `frontend/src/screens/MarketingScreen.module.css` | Segment builder, DSL expander, saved table, coupon row |
| `frontend/src/screens/MarketingScreen.segments.test.tsx` | **NEW** — compile → preview count → save; delete confirm |
| `frontend/src/screens/MarketingScreen.broadcast.test.tsx` | **NEW** — mutual exclusivity; coupon in payload; segment vs RFM labels |

**`marketingApi.ts` additions:**

```typescript
export async function compileSegment(plain_english: string): Promise<SegmentCompileResponse>
export async function previewSegment(dsl: object): Promise<{ preview_count: number }>
export async function createSegment(body: { name: string; dsl: object; plain_english?: string }): Promise<SegmentResponse>
export async function deleteSegment(id: number): Promise<void>
export async function fetchSegments(): Promise<SegmentResponse[]>
```

#### 4.2.8 Dish-aware compile (ordered_dish_id)

Plain English like "ordered biryani 3+ times" requires mapping dish **names** → `ordered_dish_id` integer.

**Phase 2 includes:**

1. `dish_catalog_for_compiler` returns up to 200 active dishes `{ id, name }` for the tenant.
2. Append catalog to compile prompt context (service builds enriched string OR passes catalog to a new compiler method — prefer enriching `plain_english` suffix):

   ```
   {manager text}

   Active menu dishes (use ordered_dish_id with these ids only):
   - 12: Chicken Biryani
   - 15: Mutton Biryani
   ```

3. LLM emits `{"field":"ordered_dish_id","op":"eq","value":12,"min_count":3}`.
4. If dish not found in catalog, compiler may omit dish clause — preview count reflects what's parseable; manager sees low count and revises.

**Out of scope Phase 2:** fuzzy dish picker UI, multi-dish OR segments (compiler may emit `any` tree — supported by DSL).

#### 4.2.9 Backend files

| File | Change |
|------|--------|
| `src/app/marketing/schemas.py` | New compile/preview models; extend `SegmentResponse` |
| `src/app/marketing/service.py` | `compile_segment_from_english`, `preview_segment`, `delete_segment`, `dish_catalog_for_compiler` |
| `src/app/marketing/router.py` | compile, preview, delete routes; broadcast mutual exclusivity + coupon validate + stats metadata |
| `src/app/menu/service.py` (or existing list helper) | Read-only dish list for compiler — **router calls marketing service only** |
| `tests/marketing/test_router.py` | compile, preview, delete, broadcast segment_id, broadcast mutual exclusivity, coupon |
| `tests/marketing/test_service.py` | compile + delete guards |
| `tests/marketing/test_segments.py` | unchanged + integration with dish catalog mock |

#### 4.2.10 Tests (Phase 2 exit criteria)

**Backend**

- [ ] `test_compile_segment_returns_dsl_and_count` (FakeSegmentCompiler via test env)
- [ ] `test_compile_segment_rejects_invalid_dsl_from_compiler` (monkeypatch bad output)
- [ ] `test_preview_segment_validates_dsl`
- [ ] `test_delete_segment_not_found`
- [ ] `test_delete_segment_success`
- [ ] `test_broadcast_with_segment_id_targets_subset`
- [ ] `test_broadcast_rejects_segment_and_rfm_together`
- [ ] `test_broadcast_with_coupon_value_issues_codes` (customer with order)
- [ ] `test_broadcast_coupon_skipped_when_no_order` (still queued)

**Frontend**

- [ ] Segments tab: compile shows count; save appears in table
- [ ] WhatsApp: selecting segment clears RFM; send payload correct
- [ ] Coupon field serializes to `coupon_value` string

**Regression**

- [ ] `pytest tests/marketing/` green
- [ ] `ruff check` on touched files
- [ ] Graphify update on changed files

#### 4.2.11 Phase 2 open decisions (locked defaults)

| # | Decision | Choice |
|---|----------|--------|
| P2-Q1 | Audit compile requests? | **No** — read-only |
| P2-Q2 | Edit saved segment in Phase 2? | **No** — delete + recreate (edit in Phase 3+) |
| P2-Q3 | Coupon on Today's Special? | **No** — broadcast only |
| P2-Q4 | `ordered_dish_id` without catalog match | Compile succeeds; clause may be omitted; manager uses count as feedback |

---

### Phase 3 — Less manager friction (template lifecycle)

**Depends on:** Phases 1–2 can proceed in parallel; Phase 3 touches template create/submit flows used by all tabs.  
**Priority:** Third implementation slice.  
**Note:** Much of the backend already exists (`poll_template_statuses`, `cleanup_ephemeral_templates`, resumable image upload in `template_meta.py`, Celery beats in `celery_app.py`). Phase 3 is primarily **UI polish + fix-and-resubmit + ephemeral/fallback wiring + verification tests**.

#### 4.3.1 User stories

1. As a manager, I see where my template is in the Meta approval pipeline without manually clicking Refresh.
2. As a manager, a pending template preview visibly "processes" (shimmer + timeline) so I know the platform is working.
3. As a manager, when Meta rejects a template I click **Fix with AI**, review the revised message, and resubmit in one flow.
4. As a manager, templates I create for **Today's Special** are automatically ephemeral and cleaned up end-of-day without me deleting them.
5. As a manager, if today's special template is rejected, a pre-approved **fallback template** still goes out (if configured).
6. As a manager, image-header templates work in production when `APP_WA_APP_ID` is set (resumable Meta upload verified by tests).

#### 4.3.2 Template status → UI mapping

| DB `status` | Timeline step | Preview chrome | Send / Save |
|-------------|---------------|----------------|-------------|
| `draft` | Draft (not shown in pill list today) | Normal | Submit only |
| `pending_meta` | Submitted + Pending active | Shimmer + indigo accent | Disabled |
| `approved` | All steps complete | Green flash on transition | Enabled |
| `rejected` | Pending step failed (red) | Rejection banner | Fix with AI → resubmit |
| `deleted` | Hidden from all lists | — | — |

Draft rows stay hidden from pill lists (noise); managers only see templates after first submit — unchanged.

#### 4.3.3 UI — `ApprovalTimeline` component

**New file:** `frontend/src/components/ApprovalTimeline.tsx` (+ `.module.css`)

Horizontal stepper below the WhatsApp preview on WhatsApp tab, Today's Special tab, and create modal (after submit returns pending).

```
  ●────────●────────◐────────○
 Draft   Submitted  Pending   Approved
```

| Step | Active when | Complete when |
|------|-------------|---------------|
| Draft | never shown post-submit (implicit) | on submit |
| Submitted | `pending_meta` (first 2s after submit toast) | immediately with pending |
| Pending | `pending_meta` | `approved` or `rejected` |
| Approved | `approved` | terminal |
| Failed | `rejected` — Pending node turns red ✕ | terminal until resubmit |

**Rejected state:**

```
[ Meta rejected this template ]
{rejection_reason}
[ ✨ Fix with AI ]  [ Edit manually ]
```

- **Fix with AI** → `fixTemplate(id)` → pre-fills body in create modal (or inline editor) → manager clicks **Submit for approval** again.
- **Edit manually** → opens create modal with current body/footer/header.

**Approved transition animation (design brief §3.3):**

- Remove shimmer class
- `.previewApprovedFlash` — one-shot 400ms border pulse `--sla-safe`
- Toast: "Template approved — ready to send ✅"

#### 4.3.4 UI — Pending shimmer on `TemplatePreview`

**CSS** (`MarketingScreen.module.css` + design brief):

```css
/* 1.6s left-to-right sweep while pending_meta */
.previewShimmer::after {
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(129, 140, 248, 0.18) 50%,
    transparent 100%
  );
  animation: shimmerSweep 1.6s ease-in-out infinite;
}
```

Apply `previewShimmer` to `.bubble` when `status === "pending_meta"`.

#### 4.3.5 UI — Auto-poll (replace manual Refresh as primary)

**Hook** in `MarketingScreen.tsx`:

```typescript
const hasPending = templates.some((t) => t.status === "pending_meta");
usePoll(fetchTemplates, hasPending ? 30_000 : null); // null = disabled
```

- While any template is `pending_meta`, reload templates every **30s** (UI layer; server beat is **2 min** via `APP_MARKETING_TEMPLATE_POLL_MINUTES`).
- **↻ Refresh** button remains as secondary/debug on pending templates (ghost, smaller).
- On status transition `pending_meta → approved` detected in poll diff → trigger approved flash + toast.

#### 4.3.6 UI — Ephemeral flag on create

**Context flag** when opening create modal:

| Opened from | `ephemeral` on `POST /templates` |
|-------------|-----------------------------------|
| WhatsApp tab · ＋ New template | `false` (reusable promo) |
| Today's Special tab · ＋ New template | `true` (daily special — EOD delete) |

Extend create modal footer hint when ephemeral: "This template is for today only — removed automatically tonight."

#### 4.3.7 UI — Today's Special fallback template

**Extend `TodaysSpecial` settings shape:**

```typescript
type TodaysSpecial = {
  enabled: boolean;
  template_id: number | null;           // primary
  fallback_template_id: number | null;  // NEW — optional
  lead_minutes: number;
  default_time: string;
  window_start: string | null;
  window_end: string | null;
};
```

**New card** on Today's Special tab (below primary template picker):

```
Fallback template (optional)
If today's template isn't approved in time, we'll send this one instead.
[Pills: same approved templates + None]
```

- Save blocked only if **enabled** and **both** primary and fallback are set but neither is approved (same rule as today for primary alone).
- If primary is `pending_meta` or `rejected` but fallback is `approved` → Save allowed; tick uses fallback (see §4.3.10).

**Warning banner** when primary `rejected` and no fallback configured:

```
Today's template was rejected. Add a fallback or fix and resubmit before enabling.
```

#### 4.3.8 API — new and extended endpoints

**Extend `TemplateCreate`:**

```python
class TemplateCreate(BaseModel):
    # ... existing fields ...
    ephemeral: bool = False  # NEW — default reusable promo
```

**New fix endpoint:**

```
POST /api/v1/marketing/templates/{id}/fix
  Response: TemplateDraftResponse  # { suggested_name, body, footer, examples }
```

**`TemplateFixRequest`** — optional override (Phase 3 uses rejection from row only):

```python
class TemplateFixRequest(BaseModel):
    hint: str | None = None  # optional manager note to the AI
```

**Fix flow (router → service → copywriter):**

1. Load `WaTemplate` — must be `status == "rejected"` and belong to tenant.
2. `fix_template_body(restaurant_name, body, rejection_reason, hint?)` in `copywriter.py`.
3. Run `lint_template` on revised body — if violations, return 422 with lint messages (don't return bad body).
4. Return `TemplateDraftResponse` — **does not** persist or auto-submit (manager confirms).
5. On resubmit: existing `POST /templates/{id}/submit` after manager updates body via `PATCH` — **add**:

```
PATCH /api/v1/marketing/templates/{id}
  Body: { body?, footer?, header?, buttons? }
  Response: TemplateResponse
  Guard: only when status in (draft, rejected) — rejected → reset status draft before resubmit
```

`PATCH` is required because fix returns draft text but the stored row still has the rejected body until updated.

**Simpler Phase 3 alternative (locked):** `fix` endpoint updates `tpl.body` in DB, sets `status="draft"`, clears `rejection_reason`, returns `TemplateResponse`. Manager clicks **Submit for approval** — one less PATCH endpoint.

| Approach | Choice |
|----------|--------|
| Fix persists to DB | **Yes** — fix writes body + `status=draft` + clear rejection |
| Separate PATCH | Deferred — not needed if fix persists |

#### 4.3.9 Copywriter — `fix_template_body`

**New prompt** in `src/app/llm/prompts_marketing.py`:

```python
TEMPLATE_FIX_PROMPT = (
    "[ROLE]\nYou revise rejected WhatsApp marketing templates.\n\n"
    "[INPUT]\n"
    "Restaurant: {restaurant}\n"
    "Rejection reason: {rejection_reason}\n"
    "Original body: {body}\n"
    "Manager hint: {hint}\n\n"
    "[CONSTRAINTS]\n"
    "Same rules as COPYWRITER_PROMPT + directly address the rejection reason.\n"
    "Keep {{{{1}}}} exactly once.\n\n"
    "[OUTPUT]\n"
    'JSON only: {{"body": "...", "footer": "Reply STOP to opt out"}}'
)
```

**`fix_template_body` in `copywriter.py`:**

- Same provider routing as `draft_template` (deepseek / claude / rule-based fallback).
- Fallback: strip problematic patterns mentioned in rejection (URLs, emoji runs) heuristically.
- Service calls `lint_template` before persisting.

#### 4.3.10 Backend — ephemeral cleanup side effects

**Enhance `cleanup_ephemeral_templates`** (`service.py`):

After soft-deleting an ephemeral template:

1. Query restaurants where `settings.todays_special.template_id == tpl.id` OR `fallback_template_id == tpl.id`.
2. For each, patch settings JSONB:
   - Clear `template_id` if it matched
   - Clear `fallback_template_id` if it matched
3. `record_audit` per restaurant settings change (`todays_special.template_cleared`).

**Frontend on reload:** if selected special template missing from list → toast "Today's template was removed (end of day). Pick a new one."

#### 4.3.11 Backend — fallback resolution in tick

**New helper** `resolve_todays_special_template(session, restaurant, cfg) -> WaTemplate | None`:

```python
async def resolve_todays_special_template(session, restaurant, cfg) -> WaTemplate | None:
    for tid in (cfg.get("template_id"), cfg.get("fallback_template_id")):
        if not tid:
            continue
        tpl = await session.get(WaTemplate, tid)
        if tpl and tpl.restaurant_id == restaurant.id and tpl.status == "approved":
            return tpl
    return None
```

Replace direct `template_id` lookup in `run_todays_special_tick` (lines 633–638). Log which template was used in campaign metadata: `stats["template_source"] = "primary" | "fallback"`.

#### 4.3.12 Meta image upload — verification (not rewrite)

`template_meta.py` already implements resumable upload (`_upload_image_header`). Phase 3 deliverables:

| Item | Action |
|------|--------|
| Unit test | `tests/marketing/test_template_meta_upload.py` — mock httpx two-step upload returns handle |
| Integration test | Submit IMAGE template with `marketing_template_provider=meta` + mocked Graph — assert handle in payload |
| Router guard | Already returns 422 when `APP_WA_APP_ID` missing — keep |
| Docs in UI | Create modal image hint: "Requires Facebook App ID in server config" (tooltip on upload error) |

**No rewrite** unless test proves a bug.

#### 4.3.13 Workers — verify Celery beat (already wired)

From `apps/workers/celery_app.py` (confirm in Phase 3 QA checklist):

| Beat key | Task | Schedule |
|----------|------|----------|
| `marketing-poll-template-statuses` | `marketing.poll_template_statuses` | `*/{marketing_template_poll_minutes}` (default 2 min) |
| `marketing-cleanup-ephemeral-templates` | `marketing.cleanup_ephemeral_templates` | `{ephemeral_delete_hour}:{ephemeral_delete_minute}` Asia/Dubai (default 23:30) |

**Phase 3 tests already exist:** `tests/marketing/test_worker.py`, `test_service.py` poll/cleanup — extend for settings-clear side effect only.

#### 4.3.14 Frontend files

| File | Change |
|------|--------|
| `frontend/src/components/ApprovalTimeline.tsx` | **NEW** — stepper + rejected actions |
| `frontend/src/components/ApprovalTimeline.module.css` | **NEW** — steps, failed state, shimmer keyframes shared or imported |
| `frontend/src/lib/marketingApi.ts` | `fixTemplate(id, hint?)`, extend `createTemplate` with `ephemeral`; optional `updateTemplate` if PATCH added |
| `frontend/src/screens/MarketingScreen.tsx` | Timeline under preview; shimmer class; auto-poll; fix flow; ephemeral flag; fallback picker; rejection banners |
| `frontend/src/screens/MarketingScreen.module.css` | Shimmer, approved flash, fallback card, rejection banner |
| `frontend/src/screens/MarketingScreen.templates.test.tsx` | **NEW** — timeline states, fix button calls API, ephemeral flag on create |

#### 4.3.15 Backend files

| File | Change |
|------|--------|
| `src/app/marketing/schemas.py` | `ephemeral` on `TemplateCreate`; `TemplateFixRequest` optional |
| `src/app/marketing/copywriter.py` | `fix_template_body()` |
| `src/app/llm/prompts_marketing.py` | `TEMPLATE_FIX_PROMPT` |
| `src/app/marketing/router.py` | `POST /templates/{id}/fix`; pass `ephemeral` to `WaTemplate` on create |
| `src/app/marketing/service.py` | `fix_template()` service; `resolve_todays_special_template()`; cleanup settings side effect |
| `src/app/identity/models.py` | Add `fallback_template_id: None` to `DEFAULT_SETTINGS["todays_special"]` |
| `tests/marketing/test_router.py` | fix endpoint, ephemeral create, rejected→fix→resubmit |
| `tests/marketing/test_template_meta_upload.py` | **NEW** — httpx mock resumable upload |
| `tests/marketing/test_service.py` | fallback resolution; cleanup clears settings |

#### 4.3.16 Tests (Phase 3 exit criteria)

**Backend**

- [ ] `test_create_template_ephemeral_flag_persisted`
- [ ] `test_fix_template_rejected_returns_revised_body_and_sets_draft`
- [ ] `test_fix_template_rejects_non_rejected`
- [ ] `test_fix_template_fails_lint_returns_422`
- [ ] `test_resubmit_after_fix_approves` (mock provider)
- [ ] `test_todays_special_tick_uses_fallback_when_primary_rejected`
- [ ] `test_cleanup_ephemeral_clears_todays_special_template_id_in_settings`
- [ ] `test_meta_image_upload_resumable_mock_httpx`

**Frontend**

- [ ] Pending template shows shimmer class
- [ ] Approval timeline shows correct step for each status
- [ ] Fix with AI → body updates → resubmit button enabled
- [ ] Create from Today's Special sends `ephemeral: true`

**Workers / regression**

- [ ] `tests/marketing/test_worker.py` still green
- [ ] Celery beat entries present (smoke import `celery_app.conf.beat_schedule`)
- [ ] `ruff check` + graphify update

#### 4.3.17 Phase 3 open decisions (locked defaults)

| # | Decision | Choice |
|---|----------|--------|
| P3-Q1 | Fix persists to DB or return-only? | **Persist** — body updated, `status=draft`, rejection cleared |
| P3-Q2 | UI poll interval vs server beat | **30s UI** + **2min server** (both) |
| P3-Q3 | Reusable promo `ephemeral` default | **`false`** on WhatsApp create |
| P3-Q4 | Clear settings on EOD delete | **Yes** — backend clears stale `template_id` / `fallback_template_id` |
| P3-Q5 | PATCH template endpoint | **Deferred** — fix endpoint writes body directly |

---

### Phase 4 — Drive repeat orders (Automation tab)

**Depends on:** Phase 2 (optional segment override on cards); Phase 3 (approved template lifecycle).  
**Priority:** Fourth implementation slice.  
**Note:** `recurring_message_state` + `recurring_promo_tick` were planned in Phase 6 Task 17 but **not yet migrated**; `marketing_automations` table never shipped. Phase 4 implements presets via **hard-coded evaluators** (not full Klaviyo trigger/condition/action DSL — that is Phase 4b / Phase 7).

#### 4.4.1 User stories

1. As a manager, I enable preset automations (welcome, win-back, reorder, recurring) each with an approved template.
2. As a manager, I optionally limit an automation to a saved segment instead of all customers.
3. As a new customer, after my first delivered order I receive a welcome promo ~1 hour later (if opted in and under cap).
4. As a repeat customer, after each order I enter the recurring promo schedule (day +3, then weekly at usual time −15 min).
5. As a lapsed customer (60+ days), I receive a win-back message (at most once per 60-day window).
6. As a habitual customer, I get a reorder reminder shortly before my usual order time on days I typically order.
7. As a manager, I see last-run stats (sent / converted) on each automation card.

#### 4.4.2 Architecture — preset automations (not full DSL)

Phase 4 ships **four fixed presets** backed by `marketing_automations` rows and Python evaluators in `marketing/automations.py`. Custom plain-English automations (spec §4.7 Klaviyo-style) are **Phase 4b** — UI shows collapsed "Advanced — coming soon".

```
┌──────────────────┐     order.delivered      ┌─────────────────────────┐
│ dispatch/        │ ─────────────────────────► │ marketing.service       │
│ advance_delivery │   on_order_delivered()   │ · seed recurring state  │
└──────────────────┘   (best-effort)         │ · schedule welcome +1h  │
                                               └───────────┬─────────────┘
                                                           │
         ┌─────────────────────────────────────────────────┼──────────────────────┐
         ▼                         ▼                       ▼                      ▼
  automation_tick (*/15)   recurring_promo_tick (hourly)  send_scheduled (*/5)   run_campaign_send
  · welcome due campaigns    · RecurringMessageState due  · scheduled campaigns  · per-customer compliance
  · reorder reminders        · advance day3 → weekly        · welcome +1h          · opt-out/cap/window
  · winback daily slice
```

**Order-delivered hook (locks Q4):** Best-effort call inside `dispatch/delivery.py:advance_delivery` when `to_status == "delivered"`, **after** `recompute_customer_stats` — same pattern as loyalty `earn()` (lines 86–100). Marketing must never block delivery.

```python
if to_status == "delivered":
    try:
        from app.marketing.service import on_order_delivered
        await on_order_delivered(session, order=order)
    except Exception:
        pass  # marketing never blocks delivery
```

#### 4.4.3 Migration — new tables

**`marketing_automations`**

| Column | Type | Notes |
|--------|------|-------|
| id | bigint PK | |
| restaurant_id | FK `restaurants.id` | tenant |
| preset_key | varchar(16) | `welcome` \| `winback` \| `reorder` \| `recurring` |
| enabled | bool | default `false` |
| template_id | FK `wa_templates.id` | nullable |
| segment_id | FK `segments.id` | nullable — audience override |
| config | JSONB | preset-specific knobs (see §4.4.5) |
| stats | JSONB | `{ sent, converted, last_queued, last_suppressed }` rolling |
| last_run_at | timestamptz | nullable |
| created_at / updated_at | timestamptz | `TimestampMixin` + `trg_marketing_automations_updated_at` |

**Unique constraint:** `(restaurant_id, preset_key)`.

**`recurring_message_state`** (per Phase 6 Task 17 + spec §3)

| Column | Type | Notes |
|--------|------|-------|
| id | bigint PK | |
| restaurant_id | FK | tenant |
| customer_id | FK `customers.id` | |
| next_send_at | timestamptz | UTC |
| suppressed_until | timestamptz | nullable — pause promos |
| phase | varchar(8) | `day3` \| `weekly` |
| weekday | smallint | 0=Mon … 6=Sun (Dubai local order day) |
| usual_send_local_time | varchar(5) | `"HH:MM"` Dubai — send at this local time −15 min |
| created_at / updated_at | timestamptz | trigger |

**Unique constraint:** `(restaurant_id, customer_id)`.

**`marketing_automation_sends`** (dedup ledger — prevents repeat welcome / winback spam)

| Column | Type | Notes |
|--------|------|-------|
| id | bigint PK | |
| restaurant_id | FK | |
| automation_id | FK `marketing_automations.id` | |
| customer_id | FK | |
| sent_at | timestamptz | |
| campaign_id | FK `campaigns.id` | nullable |

**Unique constraint:** `(automation_id, customer_id)` for welcome; winback uses time-window check instead (see §4.4.5).

Register models in `alembic/env.py` + `tests/conftest.py`.

#### 4.4.4 Preset definitions

| `preset_key` | UI title | Trigger | Action | Default config |
|--------------|----------|---------|--------|----------------|
| `welcome` | Welcome offer | First delivered order (`total_orders == 1` after stats refresh) | Schedule single-recipient campaign `scheduled_at = now + 1h` | `{ "delay_hours": 1 }` |
| `recurring` | Recurring promo | Each delivered order | Upsert `recurring_message_state`: first `day3` at order_date+3 @ usual−15m; after first send → `weekly` | `{ "lead_minutes": 15 }` |
| `winback` | Win-back | `last_order_days_ago > 60` (built-in segment) | Daily automation tick sends to matches; max 1 per customer per 60d | `{ "lapsed_days": 60, "cooldown_days": 60 }` |
| `reorder` | Reorder reminder | Habitual customer (`predict_order_time` trusted) on matching weekday | Same minute-of-day logic as Today's Special `is_due()` with automation `lead_minutes` | `{ "lead_minutes": 15 }` |

**Shared guards (all presets):** `is_opted_out` → skip; `can_send_marketing` (cap + window); template must be `approved`; segment override limits audience when set.

#### 4.4.5 Evaluator details (`marketing/automations.py`)

**`on_order_delivered(session, *, order: Order)`**

1. Load enabled `welcome` automation for `order.restaurant_id`.
2. If enabled + template approved + customer `total_orders == 1`:
   - Skip if `marketing_automation_sends` already has row for this automation+customer.
   - `create_campaign(type="automation", template_id=..., scheduled_at=now+1h)`.
   - Store `audience_ids=[order.customer_id]` on campaign via stats JSON `{"audience_ids": [id]}` for `run_campaign_send` (extend send to read from stats when present).
3. Load enabled `recurring` automation.
4. If enabled: `upsert_recurring_state(session, order=order, lead_minutes=config.lead_minutes)`:
   - `weekday` = Dubai local weekday of `order.delivered_at`
   - `usual_send_local_time` from `predict_order_time` or `customers.usual_order_time`
   - `phase = "day3"`, `next_send_at` = delivered_date + 3 days at usual−lead

**`run_automation_tick(session, now_utc)`** — */15 min

| Preset | Logic |
|--------|-------|
| `welcome` | Handled by `send_scheduled_campaigns` (due `scheduled_at`) — tick only flips stats |
| `reorder` | For each enabled `reorder`: mirror `run_todays_special_tick` per-customer `is_due()` but use automation template + optional segment filter |
| `winback` | Once daily slice (Dubai midnight boundary): evaluate built-in DSL `{all:[{field:last_order_days_ago,op:gt,value:60}]}` intersect segment; exclude cooldown window |

**`run_recurring_promo_tick(session, now_utc)`** — hourly

1. Select `recurring_message_state` where `next_send_at <= now` and (`suppressed_until` is null or past).
2. Join enabled `recurring` automation + approved template for restaurant.
3. Per row: `_send_to_customer` via ephemeral per-tick campaign (same pattern as Today's Special `ensure_todays_special_campaign`).
4. Advance state:
   - `phase == "day3"` → set `phase = "weekly"`, `next_send_at` = same weekday next week at `usual_send_local_time − lead`
   - `phase == "weekly"` → `next_send_at += 7 days` (recompute `usual_send_local_time` from `usual_order_times` for habit drift)

**Campaign `type` strings:** `automation` for welcome/winback/reorder; `recurring` for recurring promo tick.

#### 4.4.6 API

**Seed on first access:** `GET /api/v1/marketing/automations` ensures four preset rows exist (disabled, no template).

```python
class AutomationConfig(BaseModel):
    delay_hours: int | None = None       # welcome
    lead_minutes: int | None = None        # recurring, reorder
    lapsed_days: int | None = None       # winback
    cooldown_days: int | None = None     # winback

class AutomationResponse(BaseModel):
    preset_key: str
    title: str                           # server-side label map
    description: str                       # manager-facing copy
    enabled: bool
    template_id: int | None
    segment_id: int | None
    segment_name: str | None             # enriched
    config: AutomationConfig
    stats: dict[str, Any]
    last_run_at: datetime | None
    save_blocked: bool                   # enabled but template not approved
    save_blocked_reason: str | None

class AutomationPatch(BaseModel):
    enabled: bool | None = None
    template_id: int | None = None
    segment_id: int | None = None        # null = all customers
    config: AutomationConfig | None = None
```

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/api/v1/marketing/automations` | List 4 presets (auto-seed) |
| `PATCH` | `/api/v1/marketing/automations/{preset_key}` | Update one preset |
| `POST` | `/api/v1/marketing/automations/{preset_key}/test` | **Optional Phase 4b** — dry-run count only |

**PATCH validation:**

- Cannot `enabled=true` without `template_id` pointing to **approved** template.
- `segment_id` must belong to tenant if set.
- `config` values clamped: `delay_hours` 1–48, `lead_minutes` 5–120, `lapsed_days` 30–180.

**Audit:** `automation.enabled`, `automation.updated` on PATCH.

#### 4.4.7 UI — Automation tab

Replace "Coming soon" placeholder with **four preset cards** (stacked, full width).

```
┌─────────────────────────────────────────────────────────────────┐
│ AUTOMATIONS                                                      │
│ Hands-off messages triggered by customer behaviour.               │
├─────────────────────────────────────────────────────────────────┤
│ ┌─ Welcome offer ──────────────────────────────── [toggle ON] ─┐ │
│ │ Send a one-time promo 1 hour after a customer's first order. │ │
│ │ Template: [Friday promo ▼]   Segment: [All ▼] optional      │ │
│ │ Last run: 12 sent · 3 orders    [mini sparkline optional]    │ │
│ └──────────────────────────────────────────────────────────────┘ │
│ ┌─ Recurring promo ──────────────────────────── [toggle OFF] ─┐ │
│ │ Day 3 after each order, then weekly same day −15 min.         │ │
│ │ Template: [Select…]   Lead: [15|30|45] min pills              │ │
│ └──────────────────────────────────────────────────────────────┘ │
│ ┌─ Win-back ─────────────────────────────────── [toggle OFF] ─┐ │
│ │ Re-engage customers inactive 60+ days.                        │ │
│ └──────────────────────────────────────────────────────────────┘ │
│ ┌─ Reorder reminder ─────────────────────────── [toggle OFF] ─┐ │
│ │ Nudge habitual customers before their usual order time.       │ │
│ └──────────────────────────────────────────────────────────────┘ │
│ ▸ Advanced: custom automations (coming soon)                     │
└─────────────────────────────────────────────────────────────────┘
```

**Per-card behaviour:**

- Toggle + template pill picker (reuse `visibleTemplates` approved + pending pattern from WhatsApp tab).
- **Segment override** dropdown — "All customers" + saved segments from Phase 2 (`fetchSegments`).
- **Save** per card (PATCH on blur/toggle) or single **Save all** bar at bottom — **locked: per-card auto-save on toggle/template change** (PATCH debounced 500ms).
- `save_blocked` banner when enabled without approved template (mirror Today's Special).
- Stats from `automation.stats` + live conversion from latest linked campaigns (optional enrich on GET).

**Advanced section (Phase 4b):** Collapsed accordion, disabled — "Build custom trigger/condition/action rules in plain English — coming soon."

#### 4.4.8 Workers — new + fixed schedules

| Task | Schedule (Asia/Dubai) | Status |
|------|----------------------|--------|
| `marketing.send_scheduled_campaigns` | `*/5` min | **Change** from daily 9am only → */5 for welcome +1h |
| `marketing.automation_tick` | `*/15` min | **NEW** |
| `marketing.recurring_promo_tick` | hourly (`minute=0`) | **NEW** |

Add to `apps/workers/celery_app.py` beat_schedule; implement tasks in `marketing/worker.py` calling service functions.

**Extend `run_campaign_send`:** When `campaign.stats` contains `audience_ids: list[int]`, use that list instead of segment/all (welcome single-customer sends).

#### 4.4.9 Frontend files

| File | Change |
|------|--------|
| `frontend/src/lib/marketingApi.ts` | `fetchAutomations`, `patchAutomation` |
| `frontend/src/lib/types.ts` or marketingApi | `AutomationResponse`, `AutomationPatch` |
| `frontend/src/screens/MarketingScreen.tsx` | Replace automation placeholder with `AutomationCards` |
| `frontend/src/screens/MarketingScreen.module.css` | Automation card layout |
| `frontend/src/screens/MarketingScreen.automations.test.tsx` | **NEW** — toggle, template required, PATCH payload |

**Optional extract:** `frontend/src/components/AutomationCard.tsx` if `MarketingScreen` exceeds ~1500 lines (trigger nested routes refactor).

#### 4.4.10 Backend files

| File | Change |
|------|--------|
| `src/app/marketing/models.py` | `MarketingAutomation`, `RecurringMessageState`, `MarketingAutomationSend` |
| `alembic/versions/<hash>_marketing_automations.py` | Tables + triggers |
| `src/app/marketing/automations.py` | **NEW** — preset evaluators, builtin winback DSL |
| `src/app/marketing/service.py` | `on_order_delivered`, `run_automation_tick`, `run_recurring_promo_tick`, `ensure_automation_presets`, `patch_automation` |
| `src/app/marketing/router.py` | GET/PATCH automations |
| `src/app/marketing/schemas.py` | Automation I/O models |
| `src/app/marketing/worker.py` | `automation_tick`, `recurring_promo_tick` tasks |
| `src/app/dispatch/delivery.py` | `on_order_delivered` hook |
| `apps/workers/celery_app.py` | Beat entries + */5 scheduled sends |
| `tests/marketing/test_automations.py` | **NEW** |
| `tests/marketing/test_worker.py` | recurring + automation tick |
| `tests/dispatch/test_delivery.py` | delivered calls marketing hook (mock) |

#### 4.4.11 Tests (Phase 4 exit criteria)

**Backend**

- [ ] `test_ensure_automation_presets_seeds_four_rows`
- [ ] `test_patch_automation_requires_approved_template_when_enabled`
- [ ] `test_on_order_delivered_schedules_welcome_for_first_order`
- [ ] `test_on_order_delivered_skips_welcome_when_not_first_order`
- [ ] `test_on_order_delivered_upserts_recurring_state_day3`
- [ ] `test_recurring_promo_tick_sends_and_advances_to_weekly`
- [ ] `test_winback_tick_respects_cooldown`
- [ ] `test_reorder_tick_uses_is_due_logic`
- [ ] `test_scheduled_welcome_campaign_sends_single_customer`
- [ ] `test_advance_delivery_invokes_on_order_delivered`

**Frontend**

- [ ] Automation tab renders four cards
- [ ] Enable without template shows blocked state
- [ ] Toggle PATCH includes `template_id` and `enabled`

**Workers**

- [ ] Celery beat includes `automation_tick`, `recurring_promo_tick`, `send_scheduled_campaigns` */5

#### 4.4.12 Phase 4 open decisions (locked defaults)

| # | Decision | Choice |
|---|----------|--------|
| P4-Q1 | Order hook location | **`advance_delivery`** best-effort (same txn as delivery) |
| P4-Q2 | Full Klaviyo DSL in Phase 4? | **No** — presets only; Advanced = Phase 4b |
| P4-Q3 | Welcome delivery mechanism | **Scheduled campaign** `now+1h` + */5 send tick |
| P4-Q4 | Win-back frequency | **Daily** tick + 60d per-customer cooldown |
| P4-Q5 | Auto-save vs Save bar | **Per-card debounced PATCH** |
| P4-Q6 | `custom` preset row | **Not seeded** until Phase 4b |

#### 4.4.13 Phase 4b (out of scope, documented)

- Plain-English trigger/condition/action compiler (new LLM port)
- `marketing_automations` rows with `preset_key=custom` + `trigger_dsl` / `condition_dsl` / `action_dsl`
- UI Advanced accordion builder (design brief § Screen 5 — Automations)

---

### Phase 5 — AI media, scheduled broadcast, studio polish

**Depends on:** Phases 1–4 (template create flow, broadcast, compliance pipeline).  
**Priority:** Fifth slice — polish and power features after core studio is live.  
**Non-goals:** Campaign A/B testing, video header templates, custom automation DSL (Phase 4b), nested-route refactor unless `MarketingScreen` forces it.

#### 4.5.1 User stories

1. As a manager, I generate a promo header image from my offer text instead of uploading a file.
2. As a manager, I schedule a broadcast for a future date/time (Dubai-local picker) instead of sending immediately.
3. As a manager, I cancel or reschedule a queued broadcast before it fires.
4. As a manager, I see scheduled campaigns in the Campaigns tab with status `scheduled` and their fire time.
5. As a platform operator, image generation uses a swappable port (fake/Pillow in tests, real provider in prod) — never hits paid APIs in CI.

#### 4.5.2 AI header image generation

**Pattern:** New port behind factory (same as `TemplatePort`, `SegmentCompiler`, `pos/images.py` placeholder).

```
src/app/marketing/
  image_port.py      Protocol + PromoImageSpec
  image_placeholder.py   Pillow deterministic promo (tests/dev default)
  image_openai.py    optional DALL-E / compatible API (prod)
  image_factory.py   get_promo_image_generator() — APP_MARKETING_IMAGE_PROVIDER
```

**`PromoImageGeneratorPort`:**

```python
class PromoImageGeneratorPort(Protocol):
    async def generate(self, *, prompt: str, restaurant_name: str) -> bytes:
        """Return PNG or JPEG bytes, ≥500×500 px (Meta catalog/header guidance)."""
```

**Providers:**

| Provider key | Implementation | When |
|--------------|----------------|------|
| `placeholder` | Pillow promo card (extend `pos/images.py` style — dish photo aesthetic, restaurant name watermark) | tests, dev default |
| `openai` | DALL-E 3 (or configured endpoint) when `APP_OPENAI_API_KEY` set | prod optional |
| `claude` | **Not in Phase 5** — Claude has no image output API; do not block on it |

**Prompt construction** (`marketing/image_prompt.py`):

```
Restaurant: {restaurant_name}
Offer: {describe or body excerpt}
Style: appetizing food photography, clean, no text overlay, no alcohol bottles unless offer mentions it, square 1:1
```

Manager can edit prompt in UI before generate (advanced textarea, collapsed by default).

**API:**

```
POST /api/v1/marketing/templates/image/generate
  Body: { "prompt": string, "describe"?: string }  # describe fills prompt if prompt empty
  Response: { "url": string }  # same shape as upload — stored in marketing_media
```

Flow: generate bytes → persist `MarketingMedia` row → return `/media/...` URL → manager previews in `TemplatePreview` → submit template as today.

**UI (create modal):** Enable **🖼️ Generate image** button (remove "Soon" badge). Opens mini-flow:

1. Pre-fill prompt from "Describe your offer" field
2. **Generate** → loading → preview in header slot
3. **Regenerate** / **Use uploaded instead**

**Compliance guard:** Run lightweight check on prompt (no profanity list, no guaranteed discount percentages that violate lint — optional). Generated image is visual only; `lint_template` still applies to body/footer.

**Config** (`app/config.py`):

```python
marketing_image_provider: Literal["placeholder", "openai"] = "placeholder"
marketing_image_openai_model: str = "dall-e-3"
marketing_image_max_per_day: int = 20  # per restaurant rate limit
```

**Rate limit:** Redis or DB counter per `restaurant_id` per Dubai day — 429 when exceeded.

#### 4.5.3 Video header — explicitly deferred (Phase 5+)

Meta supports VIDEO template headers (`video/mp4`, max 16 MB) but:

- Resumable upload pipeline differs from IMAGE
- Template review stricter; restaurant promos rarely need video in v1
- No existing `template_meta` video upload helper

**Phase 5 deliverable:** Keep **🎬 Generate video** disabled with tooltip: "Video promos coming later — use image or text header for now." Document spike in Phase 5+ backlog; **no API, no migration**.

#### 4.5.4 Scheduled broadcast

**Backend today:** `Campaign.scheduled_at` + `status=scheduled` + `send_scheduled_campaigns` worker exist; `POST /broadcast` always sends immediately. Phase 4 changes beat to */5 min.

**Extend `BroadcastRequest`:**

```python
class BroadcastRequest(BaseModel):
    template_id: int
    segment_id: int | None = None
    rfm_segment: str | None = None
    coupon_value: str | None = None
    type: str = "promotional"
    scheduled_at: datetime | None = None  # NEW — UTC; if set and > now, do not send now
```

**`broadcast_now` router logic:**

```python
if body.scheduled_at and body.scheduled_at > now_utc:
    camp = await create_campaign(..., scheduled_at=body.scheduled_at)  # status=scheduled
    # persist audience metadata in stats (rfm_segment, segment_id, audience_ids N/A)
    return BroadcastScheduleResponse(campaign_id=camp.id, scheduled_at=body.scheduled_at, queued=0)
else:
    # existing immediate path
```

**New response model** for scheduled path:

```python
class BroadcastScheduleResponse(BaseModel):
    campaign_id: int
    scheduled_at: datetime
    status: str = "scheduled"
```

**Cancel scheduled campaign:**

```
DELETE /api/v1/marketing/campaigns/{id}
  Guard: status == "scheduled" only → set status=cancelled, audit
  409 if already sending/sent
```

**Reschedule:**

```
PATCH /api/v1/marketing/campaigns/{id}/schedule
  Body: { "scheduled_at": datetime }
  Guard: status == "scheduled", new time > now, same validations as create
```

**Validation rules:**

| Rule | Error |
|------|-------|
| `scheduled_at` must be > now + 5 min | 422 "Schedule at least 5 minutes ahead" |
| `scheduled_at` must be ≤ now + 90 days | 422 "Cannot schedule more than 90 days out" |
| Warn (non-blocking) if Dubai local time outside 09:00–18:00 when `marketing_send_window_enabled` | Response field `window_warning: str | null` |
| Template must be **approved** at schedule time | 422 |
| Same mutual exclusivity segment vs RFM as Phase 2 | 422 |

**Worker:** No change beyond Phase 4 */5 `send_scheduled_campaigns` — scheduled broadcasts reuse `run_campaign_send` when due. Window: if due but outside UAE window, leave `scheduled` until next tick inside window (align with phase-6 plan behaviour).

#### 4.5.5 UI — WhatsApp tab schedule mode

**Send bar becomes two modes** (pill toggle above bar):

```
[ Send now ]  [ Schedule ]
```

**Send now** — unchanged (two-tap confirm).

**Schedule** — replaces send bar with:

```
Date   [ date picker ]   Time [ time picker ]  (Asia/Dubai)
       ⚠️ Sends only during 9am–6pm UAE if window enforcement is on
[ Schedule broadcast · Champions · Fri 14:30 ]
```

- Uses `Intl` / explicit `Asia/Dubai` offset helper already in frontend patterns (or `date-fns-tz` if present).
- Serializes `scheduled_at` as ISO UTC in `broadcast()` call.
- Success toast: "Scheduled for Friday 14:30 — you can cancel from Campaigns."
- Two-tap confirm retained for schedule action.

#### 4.5.6 UI — Campaigns tab (Phase 1 extension)

Add columns / badges for Phase 5:

| Status | Display |
|--------|---------|
| `scheduled` | Blue badge + local fire time |
| `cancelled` | Grey strikethrough row |

**Row actions** (scheduled only):

- **Cancel** → confirm dialog → DELETE campaign endpoint
- **Reschedule** → inline date/time → PATCH schedule

**Detail drawer:** Show scheduled fire time, window warning if stored in `campaign.stats`.

#### 4.5.7 Studio polish (optional Phase 5 bundle)

Ship if `MarketingScreen.tsx` > 1500 lines after Phase 4:

| Item | Action |
|------|--------|
| Nested routes | `/marketing/*` shell (Approach 2 from §2) |
| Reports deep link | Campaigns tab empty state → "View Reports summary" |
| Shared `CampaignSummaryStrip` | DRY with Analytics (Phase 1b) |

**Locked:** Polish items are **nice-to-have** within Phase 5 — schedule + image gen are **must-have**.

#### 4.5.8 API summary (Phase 5 new/changed)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/templates/image/generate` | AI promo header bytes → media URL |
| `POST` | `/broadcast` | Extended with `scheduled_at` branch |
| `DELETE` | `/campaigns/{id}` | Cancel scheduled campaign |
| `PATCH` | `/campaigns/{id}/schedule` | Reschedule |

#### 4.5.9 Backend files

| File | Change |
|------|--------|
| `src/app/marketing/image_port.py` | **NEW** — Protocol |
| `src/app/marketing/image_placeholder.py` | **NEW** — Pillow generator |
| `src/app/marketing/image_openai.py` | **NEW** — optional prod provider |
| `src/app/marketing/image_factory.py` | **NEW** |
| `src/app/marketing/image_prompt.py` | **NEW** — prompt builder |
| `src/app/marketing/router.py` | generate image, broadcast schedule branch, cancel, reschedule |
| `src/app/marketing/schemas.py` | `BroadcastScheduleResponse`, `SchedulePatch`, generate request |
| `src/app/marketing/service.py` | `schedule_broadcast`, `cancel_scheduled_campaign`, `reschedule_campaign`, `generate_promo_image`, rate limit |
| `src/app/config.py` | `marketing_image_provider`, limits |
| `tests/marketing/test_image_generate.py` | **NEW** |
| `tests/marketing/test_scheduled_broadcast.py` | **NEW** |

#### 4.5.10 Frontend files

| File | Change |
|------|--------|
| `frontend/src/lib/marketingApi.ts` | `generateTemplateImage`, extend `broadcast` with `scheduled_at`, `cancelCampaign`, `rescheduleCampaign` |
| `frontend/src/screens/MarketingScreen.tsx` | Generate image flow; schedule mode; campaign row actions |
| `frontend/src/screens/MarketingScreen.module.css` | Schedule picker, generate loading state |
| `frontend/src/screens/MarketingScreen.schedule.test.tsx` | **NEW** |
| `frontend/src/screens/MarketingScreen.image.test.tsx` | **NEW** |

#### 4.5.11 Tests (Phase 5 exit criteria)

**Backend**

- [ ] `test_generate_image_placeholder_returns_url`
- [ ] `test_generate_image_rate_limit_429`
- [ ] `test_broadcast_scheduled_creates_campaign_no_send`
- [ ] `test_broadcast_immediate_unchanged`
- [ ] `test_cancel_scheduled_campaign`
- [ ] `test_cancel_sent_campaign_409`
- [ ] `test_reschedule_campaign`
- [ ] `test_scheduled_tick_sends_when_due` (worker integration)

**Frontend**

- [ ] Generate image enables header preview
- [ ] Schedule mode sends `scheduled_at` UTC
- [ ] Campaigns tab shows scheduled row + cancel

#### 4.5.12 Phase 5 open decisions (locked defaults)

| # | Decision | Choice |
|---|----------|--------|
| P5-Q1 | Default image provider in prod | **`placeholder`** until OpenAI key configured |
| P5-Q2 | Video headers in Phase 5? | **No** — UI stays disabled |
| P5-Q3 | Campaign A/B | **Out of scope** — not planned |
| P5-Q4 | Schedule min lead time | **5 minutes** |
| P5-Q5 | Cancel sent campaigns? | **No** — only `scheduled` |
| P5-Q6 | Image gen prompt source | **Offer describe field** with editable override |

#### 4.5.13 Explicitly out of scope (all phases post-5)

- Campaign A/B split testing
- WhatsApp video template headers + AI video generation
- Custom automation DSL builder (Phase 4b)
- Multi-language template variants
- DNCR registry integration (UAE) — noted in compliance docs, not wired

---

## 5. Reports vs Marketing split

| Surface | Role |
|---------|------|
| **Reports (`AnalyticsScreen`)** | Aggregate KPIs: total campaigns, sent, converted, success rate % |
| **Marketing (`Campaigns` tab)** | Per-campaign table, drill-down, suppression detail |

No removal of Reports card in Phase 1 — optional later link "View all campaigns →".

---

## 6. Component reuse (design brief alignment)

| Design brief component | Phase |
|------------------------|-------|
| `TemplatePreviewCard` | Exists as `TemplatePreview` — Phase 3 adds shimmer + approved flash (§4.3.4) |
| `ApprovalTimeline` | Phase 3 — new `ApprovalTimeline.tsx` component (§4.3.3) |
| `SegmentBuilder` | Phase 2 — Segments tab builder + saved table (§4.2.3) |

---

## 7. Open questions

| # | Question | Default if unanswered |
|---|----------|----------------------|
| Q1 | Share `CampaignSummaryStrip` with Reports in Phase 1? | Yes — small shared component |
| Q2 | Campaign drawer as modal vs right drawer? | Right drawer (match `OrderDetailDrawer` pattern) |
| Q3 | Store `rfm_segment` in `Campaign.stats` vs new column? | `stats` JSON (no migration) |
| Q4 | Phase 4 order-delivered hook: sync call vs outbox event? | Outbox/event — decouple ordering from marketing |
| Q5 | Edit saved segments in Phase 2? | **No** — delete + recreate (see P2-Q2) |
| Q6 | Dish picker UI for `ordered_dish_id`? | **Phase 2b** — catalog-in-prompt only for now |
| Q7 | Fix template persist vs return-only? | **Persist** (P3-Q1) |
| Q8 | PATCH template endpoint? | **Deferred** — fix writes body (P3-Q5) |
| Q9 | Order-delivered marketing hook | **`advance_delivery`** best-effort (P4-Q1) |
| Q10 | Full automation DSL in Phase 4? | **No** — presets only (P4-Q2) |
| Q11 | Video generation in Phase 5? | **No** — disabled UI (P5-Q2) |
| Q12 | Default image provider | **placeholder** until OpenAI key (P5-Q1) |

---

## 8. Spec self-review checklist

- [x] No TBD placeholders in Phase 1
- [x] No TBD placeholders in Phase 2
- [x] No TBD placeholders in Phase 3
- [x] Backend poll/cleanup already exist — Phase 3 scoped as UI + wiring + tests
- [x] Phases map to spec §4.7 + design brief Screen 5
- [x] Scope bounded per phase (implementable plans)
- [x] Broadcast mutual exclusivity specified (segment vs RFM)
- [x] Coupon semantics documented (existing backend behaviour)
- [x] No TBD placeholders in Phase 4 (4b explicitly deferred)
- [x] Phase 4 order hook locked — `advance_delivery` (P4-Q1)
- [x] No TBD placeholders in Phase 5
- [x] Video + A/B explicitly deferred with rationale
- [ ] User review gate — pending

---

## 9. Next steps

1. User reviews this doc — request changes or approve.
2. User reviews full spec (Phases 1–5 complete).
3. Invoke **writing-plans** → `docs/superpowers/plans/2026-07-02-marketing-studio-full.md`
4. Implement Phases 1–5 with TDD (no git commit until user requests).

---

## Changelog

| Date | Change |
|------|--------|
| 2026-07-02 | Initial doc: inventory, Approach 3 approved, Phases 1–5 outlined, Phase 1 detailed (UI, API, files, tests) |
| 2026-07-03 | Phase 2 expanded: Segments tab wireframe, DSL reference, audience state machine, coupon UI, full API/service spec, dish-aware compile, broadcast mutual exclusivity, test checklist, locked decisions P2-Q1–Q4 |
| 2026-07-03 | Phase 3 expanded: ApprovalTimeline + shimmer, auto-poll, fix-with-AI (persist flow), ephemeral/fallback Today's Special, cleanup side effects, tick fallback resolution, Meta upload verification tests, worker beat QA, locked decisions P3-Q1–Q5 |
| 2026-07-03 | Phase 4 expanded: preset automations architecture, 3 new tables, four preset evaluators, order-delivered hook in advance_delivery, Automation tab UI, API GET/PATCH, workers (automation_tick, recurring_promo_tick, */5 scheduled sends), test checklist, Phase 4b deferred, locked P4-Q1–Q6 |
| 2026-07-03 | Phase 5 expanded: PromoImageGeneratorPort, image/generate API, scheduled broadcast (extend POST /broadcast, cancel/reschedule), WhatsApp schedule UI, Campaigns tab scheduled rows, rate limits, video explicitly deferred, polish bundle optional, locked P5-Q1–Q6 |