# Meta / WhatsApp Business Platform — Template Compliance Reference
**Platform use-case:** Daily AI-generated restaurant marketing template: create → approve → send → delete (end of day), repeat.
**Last verified:** 2026-06-06
**Research methodology:** Multi-source web research; official Meta developer documentation, BSP (Business Solution Provider) documentation, and third-party compliance guides. Claims marked **UNVERIFIED** where no authoritative source could confirm.

---

## Table of Contents
1. [WhatsApp Business Messaging Policy & Commerce Policy — Restaurant Marketing](#1-whatsapp-business-messaging-policy--commerce-policy--restaurant-marketing)
2. [Template Rejection Reasons Taxonomy & Review SLA](#2-template-rejection-reasons-taxonomy--review-sla)
3. [Template Content Technical Rules](#3-template-content-technical-rules)
4. [Account Health: Quality Rating, Pacing, and Template Lifecycle](#4-account-health-quality-rating-pacing-and-template-lifecycle)
5. [Marketing Frequency Capping, Opt-In/Out & UAE Rules](#5-marketing-frequency-capping-opt-inout--uae-rules)
6. [AI Generator Best-Practice Checklist for First-Pass Approval](#6-ai-generator-best-practice-checklist-for-first-pass-approval)

---

## 1. WhatsApp Business Messaging Policy & Commerce Policy — Restaurant Marketing

**Source:** [WhatsApp Business Policy](https://whatsappbusiness.com/policy/) (redirects from business.whatsapp.com/policy)

### 1.1 Food & Restaurant Marketing — Generally Permitted
Standard restaurant marketing (menus, daily specials, promotions, reservation reminders) is **not a restricted category** under the WhatsApp Commerce Policy or Business Messaging Policy. Food businesses may freely send marketing templates to opted-in customers.

### 1.2 Alcohol — Restricted, Not Banned; Country-Gated
Alcohol promotion is **permitted on the WhatsApp Business Platform API** but subject to strict conditions:

- **Geography gate:** Only permitted in ~54 approved countries. The UAE is **not confirmed** on Meta's published approved-country list — businesses must verify their specific country eligibility in Meta's Commerce Policy. **UNVERIFIED: whether UAE is currently on Meta's approved alcohol-country list.**
- **Age gating:** Alcohol messaging may not target persons under 18.
- **Local law compliance:** Must comply with all applicable local laws and industry codes (relevant in the UAE, where alcohol sale requires a licence).
- **Platform restriction:** Alcohol promotion is prohibited on the *WhatsApp Business App* (the SME consumer app); it is only permitted on the *Platform* (API).
- **Practical implication for restaurant use:** A restaurant marketing a daily special that includes an alcoholic beverage (e.g., "Today's special: grilled sea bass + house wine") should either omit the alcohol mention or verify UAE approval status. Non-alcohol food specials carry no such restriction.

### 1.3 Other Prohibited Content Categories (Relevant to Food Context)
The following are prohibited regardless of industry:
- Firearms, drugs, gambling, adult products, tobacco/e-cigarettes, body parts/fluids
- Misleading, deceptive, or fraudulent content
- Content that "confuses, deceives, defrauds, misleads, spams, or surprises people"
- Requests for sensitive personal data (full credit card numbers, government IDs, bank details)
- Offensive or sexually explicit materials

### 1.4 Promotional Content Rules
- Only **approved Message Templates** may be used to initiate conversations outside the 24-hour customer-service window
- Templates must not impersonate Meta or other companies
- Businesses must maintain **escalation paths**: human agent, phone, email, web support, or in-store
- Templates must have a clear **opt-out mechanism** (see Section 5)

### 1.5 Opt-In Requirements (Mandatory)
> "You may only contact people on WhatsApp if: (a) they have given you their mobile phone number; and (b) you have received opt-in permission from the recipient confirming that they wish to receive subsequent messages."

- Opt-in must be **explicit and informed** — the customer must know they are agreeing to receive WhatsApp messages from the specific business
- Best practice: obtain separate opt-ins per message category (marketing vs. transactional) to reduce block risk
- Opt-in collection can occur via website, in-store form, SMS, IVR, or other channels — but must be documented

---

## 2. Template Rejection Reasons Taxonomy & Review SLA

**Sources:**
- [a2c.chat — Template Rejection Analysis](https://www.a2c.chat/en/whatsapp-template-message-review-guide-5-rejection-reasons-analysis.html)
- [chakrahq.com — Template Rejection Issues](https://chakrahq.com/article/whatsapp-api-template-rejections-issues-guidelines-coexistence/)
- [Infobip Template Compliance](https://www.infobip.com/docs/whatsapp/compliance/template-compliance)
- [Wati — Meta Template Approval Updates](https://support.wati.io/en/articles/12320234-understanding-meta-s-latest-updates-on-template-approval)

### 2.1 Rejection Taxonomy

| Category | Common Causes | Notes |
|---|---|---|
| **Format Errors** (est. 30% of rejections) | Wrong variable syntax (`{1}` instead of `{{1}}`), skipped variable numbers, adjacent variables, too many variables relative to static text, full-width punctuation | Most fixable; correcting raises approval rate from ~50% to ~85% |
| **Policy / Content Violations** (est. 60% of rejections) | Prohibited products (gambling, drugs), abusive/threatening language, deceptive claims, sensitive data requests, promotion of alcohol without compliance | Templates in this category may be subject to delayed review (5–7 business days) |
| **Prohibited Links** | Shortened URLs (bit.ly, tinyurl), URLs not matching registered business domain, missing `https://`, non-mainstream TLDs | ~25% of submissions fail for this reason |
| **Category Mismatch** | Submitting a promotional template as "Utility"; since April 9, 2025, Meta **auto-reclassifies** to Marketing (with corresponding Marketing pricing applied) | Auto-reclassification can be appealed within 60 days |
| **Duplicate Content** | Template body or footer identical to an existing approved template in the same WABA | Authentication templates are exempt from this rule |
| **Missing Examples** | Not providing sample values for all variable placeholders at submission time | Meta requires examples to validate variable content intent |
| **Header Issues** | Emojis or special formatting in text headers, image not meeting spec, missing media sample | Emojis are prohibited in headers and footers |
| **Excessive Promotional Language** | More than ~2 promotional keywords ("limited-time offer", "buy now", "free", "win") in close proximity raises rejection probability significantly | Context-dependent; exact keyword threshold not officially published |
| **Excessive Whitespace/Newlines** | More than 2 consecutive newline characters, more than 4 consecutive spaces | Treated as a formatting violation |
| **Spelling/Grammar Errors** | Poor spelling, inconsistent capitalisation, grammatically broken sentences | Human reviewers flag; some automated detection |

### 2.2 Review SLA

| Scenario | Typical Duration |
|---|---|
| **Automated pass (clean template)** | 1–30 minutes (most common outcome) |
| **Standard review** | Up to 24 hours |
| **Format issue flagged** | 3–4 business days |
| **Policy violation flagged** | 5–7 business days |
| **High complaint rate account** | 7+ business days |
| **Repeated failures / restricted account** | May extend to weeks |

**Key 2025 change:** Since April 2025, Meta's automated ML classifier has become more aggressive. Templates may be auto-reclassified before content review begins. High read-rate history on the WABA correlates with faster approvals. **UNVERIFIED: exact ML model criteria for fast-track vs. human review routing.**

**Implication for daily-template design:** Plan for a potential 30-minute to 24-hour approval window. Building in a buffer (submitting the template well before the intended send time) is essential for reliability.

---

## 3. Template Content Technical Rules

**Sources:**
- [8x8 Template Components Reference](https://developer.8x8.com/connect/docs/whatsapp/template-components-reference/) — most complete technical spec found
- [Infobip Compliance Docs](https://www.infobip.com/docs/whatsapp/compliance/template-compliance)
- [WUSeller Marketing Template Rules 2025](https://www.wuseller.com/blog/whatsapp-marketing-template-format-rules-in-2025-with-ready-to-use-examples/)
- [zoko.io Character Limits](https://www.zoko.io/learning-article/character-limits-with-media-message-templates)

### 3.1 Variable Formatting
- Syntax: positional double-curly-bracket notation — `{{1}}`, `{{2}}`, `{{3}}` — or named notation `{{customer_name}}` (BSP-dependent)
- Variables must be **sequential** starting at `{{1}}`; no skipping numbers
- Variables **cannot be reused** (do not use `{{1}}` twice)
- Adjacent variables (`{{1}} {{2}}` with no static text between) are flagged as likely rejection
- There must be **sufficient static text** relative to the number of variables — a message that is mostly variables with little fixed text will be rejected
- Template body supports **unlimited parameters**; text header supports **exactly 1 parameter**; footer supports **no parameters**
- All variable placeholders must have **example values provided** at submission time
- Authentication templates: variable values must not exceed 15 characters

### 3.2 Header Specifications

| Header Type | Format | Size Limit | Recommended Dimensions | Notes |
|---|---|---|---|---|
| **Text** | Plain text | 60 characters max (incl. 1 variable) | — | No emojis, no markup, no newlines |
| **Image** | JPEG, PNG | 5 MB max | 800 × 418 px (1.91:1 ratio) | WhatsApp resizes to ~1120px wide; any aspect ratio accepted but 1.91:1 renders cleanest |
| **Video** | MP4, 3GPP | 16 MB max | Under 60 seconds recommended | — |
| **Document** | PDF, DOC, DOCX, XLS, XLSX, PPT, PPTX | 100 MB max | — | — |
| **Location** | Static map | — | — | Restricted to Utility or Marketing templates only |

**Text-in-image guidance:** WhatsApp does not publish a formal "20% text rule" (unlike Facebook Ads). However:
- Images with excessive text overlay are more likely to fail review
- Avoid: overcrowded promotional banners, pricing text, fake-urgency phrases ("100% FREE! Limited offer!!!")
- Recommended: keep image as a clean visual (food photo); convey offers in the message body, not the image
- Absolutely avoid: alcohol/tobacco imagery, adult content, gambling imagery, misleading visual claims

### 3.3 Body
- Maximum: **1,024 characters** (including all static text and variable placeholders)
- Supports bold (`*text*`), italic (`_text_`), strikethrough (`~text~`), monospace (` ```text``` `)
- Emojis are **permitted** in the body for marketing templates
- Avoid excessive newlines (max 2 consecutive) and excessive spaces (max 4 consecutive)
- Since October 2024, marketing template bodies exceeding 5 lines of text are **automatically truncated** by Meta, with a "Read more" link shown to recipients — design for scannable short messages

### 3.4 Footer
- Maximum: **60 characters**
- No parameters (variables) allowed
- No emojis (prohibited in footers)
- No markup characters
- No URLs or contact information in the footer
- Common use: opt-out instruction — e.g., "Reply STOP to unsubscribe"

### 3.5 Buttons
| Button Type | Max Count | Character Limit Per Button | Notes |
|---|---|---|---|
| **Quick Reply** | Up to 10 per template | 25 characters | For opt-out, feedback, engagement |
| **URL (Call-to-Action)** | Up to 2 per template | 25 characters (button label) | Must use full `https://` URL; no shortened URLs; supports 1 dynamic parameter at end of URL |
| **Phone Number** | 1 per template | 25 characters | — |
| **Copy Offer Code** | 1 per template | 25 characters | Copies promo code to clipboard |
| **Flow Button** | 1 per template | 25 characters | Opens a WhatsApp Flow |
| **OTP Copy Code** | 1 per template | — | Authentication only |
| **Total all types combined** | **10 buttons max** | — | — |

**For restaurant marketing:** Recommended button set = 1 URL CTA ("View Full Menu" → restaurant website) + 1 Quick Reply ("Stop") for opt-out. This is simple, compliant, and drives engagement.

### 3.6 Emoji Rules
| Section | Emoji Permitted? |
|---|---|
| Template name | No |
| Header (text) | No |
| Header (image/video) | N/A (image content, not emoji syntax) |
| Body (marketing template) | Yes |
| Footer | No |
| Button text | No official prohibition, but avoid to reduce review risk |
| Authentication template (any section) | No |

### 3.7 Language Field Requirements
- Each template submission requires a **language code** (e.g., `en`, `en_US`, `ar`, `ar_AE`)
- The declared language must **match the actual content** — mismatches (e.g., Arabic content tagged as English) are a rejection reason
- One template can have multiple language variants (translations); each variant is reviewed separately
- For UAE audiences sending in English: use `en` or `en_US`; for Arabic: use `ar`

### 3.8 Template Naming
- Lowercase alphanumeric characters and underscores **only** — no spaces, no capitals, no special characters
- Maximum 512 characters for the name
- **Critical:** After a template is deleted, the same template name **cannot be reused for 30 days**. This is a hard constraint for the daily create-delete workflow — a new unique name must be generated each day.

---

## 4. Account Health: Quality Rating, Pacing, and Template Lifecycle

**Sources:**
- [Chatarmin — WhatsApp Messaging Limits 2026](https://chatarmin.com/en/blog/whats-app-messaging-limits)
- [Cunnekt — Template Quality Rating](https://www.cunnekt.com/blog/whatsapp-template-quality-rating/)
- [InsideOne Academy — Template Pacing and Pausing](https://academy.insiderone.com/docs/whatsapp-template-pacing-and-pausing)
- [Meta Developers — Template Fundamentals](https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/overview)
- [Meta Developers — Capacity, Quality Rating, Messaging Limits](https://developers.facebook.com/docs/whatsapp/messaging-limits/)

### 4.1 Quality Rating System
Templates receive a **rolling quality score** based on the last 7 days of recipient feedback:

| Rating | Colour | Status |
|---|---|---|
| High Quality / Pending | Green | Healthy; no restrictions |
| Medium Quality | Yellow | Warning; negative feedback accumulating |
| Low Quality | Red | At risk of pausing/disabling |

**What drives the rating down:**
- Recipients blocking the business ("No Longer Needed", "No Sign-Up", "Spam", "Offensive Content")
- Low **read rate** (added as a metric April 1, 2024)
- Spam reports
- High volume of unread/unengaged messages

**Account-level cascading effects:**
1. Individual template paused: no direct WABA impact if isolated
2. Phone number **Flagged** status: triggered when multiple templates reach Low quality; blocks messaging limit tier increases for 7 days
3. Phone number **Restricted** status: sustained low quality across templates; dramatically reduces daily message volume capacity
4. WABA deactivation: extreme persistent violations

### 4.2 Template Pacing
- **Newly approved templates** are subject to a pacing period — Meta initially delivers to a subset of recipients and monitors feedback before allowing full volume
- Templates lacking a Green quality rating, newly created templates, and templates that were previously paused are all subject to pacing
- If a utility template was previously paused on the phone number, **new templates may be paced for up to 7 days**
- Marketing templates with low read rates may have their campaigns temporarily suspended (post April 1, 2024 policy)

### 4.3 Template Pause Escalation
| Occurrence | Pause Duration |
|---|---|
| First low-quality flag | 3 hours |
| Second low-quality flag | 6 hours |
| Third low-quality flag | **Permanent disable** |

- Paused templates cannot be sent; they automatically unpause after their duration
- Meta notifies via WhatsApp Manager, email, and webhook
- A permanently disabled template cannot be re-enabled; a new template must be created

### 4.4 Per-WABA Template Count Limits

| Business Portfolio Status | Template Limit per WABA |
|---|---|
| Unverified | 250 templates |
| Verified (at least one approved display name on a phone number) | **6,000 templates** |

- Template creation rate limit: **100 templates per WABA per hour**
- Templates inactive for **12 months** are automatically archived/deleted by Meta
- If the WABA limit is reached, old templates must be deleted before creating new ones

### 4.5 Template Deletion Rules — Critical for Daily Create-Delete Workflow

> **30-day name reuse blackout:** After a template is deleted, its name cannot be used again for **30 days**.

This is the single most important constraint for the daily create-delete design. The AI generator must use a unique template name each day (e.g., timestamp-based: `daily_special_20260606`).

**Does frequent deletion penalise the account?** Official Meta documentation does **not** explicitly state that frequent template creation and deletion (within allowed rate limits) penalises WABA health. However:
- Deleted templates that had **already been sent but not yet delivered** remain in a "Pending Deletion" state for up to 30 days — WhatsApp will attempt delivery during this window. Deleting before delivery confirmation is confirmed is safe for end-of-day cleanup.
- Creating templates purely to evade quality feedback (e.g., deleting a paused template and immediately recreating equivalent content under a new name) **is flagged as abuse** per Meta policy. If feedback signals suspicious activity, Meta may block the portfolio from sending or creating templates while conducting a review.
- The new template will start at "Quality Pending" (green) status with no quality history — this is normal and expected for the first sends.
- **UNVERIFIED:** Whether Meta's systems explicitly track create-delete velocity as an abuse signal. No official documentation confirms a specific cycle-per-day limit, but the abuse clause implies this risk exists.

### 4.6 Messaging Tier System (Business Portfolio Level)
Since October 2025, messaging limits apply at the **Business Portfolio level**, not per phone number:

| Tier | Daily Message Limit | Notes |
|---|---|---|
| Tier 0 (Unverified) | 250/day | Starting point |
| Tier 1 | 1,000/day | After Meta Business Verification |
| Tier 2 | 10,000/day | |
| Tier 3 | 100,000/day | |
| Tier 4 | Unlimited | Up to 1,000 MPS |

- New phone numbers in a verified portfolio **inherit the highest tier** already achieved by any number in that portfolio
- Tier advancement is blocked during "Flagged" status periods

---

## 5. Marketing Frequency Capping, Opt-In/Out & UAE Rules

**Sources:**
- [Meta Developers — Per-User Marketing Template Message Limits](https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/marketing-templates/per-user-limits/)
- [Turn.io — Per-User Limits Explained](https://learn.turn.io/l/en/article/kl493nec0m-understanding-whats-app-s-per-user-marketing-template-message-limit)
- [Infobip — What is WhatsApp Frequency Capping](https://www.infobip.com/blog/what-is-whatsapp-frequency-capping)
- [AiSensy — Frequency Capping Guide](https://m.aisensy.com/blog/meta-frequency-capping-for-whatsapp-marketing-messages/)
- [Morgan Lewis — UAE Telemarketing Regulations 2024](https://www.morganlewis.com/blogs/sourcingatmorganlewis/2024/07/telemarketing-in-an-evolving-legal-landscape-uae-adopts-regulations-on-telemarketing-activities)

### 5.1 Meta Per-User Marketing Frequency Cap
**Introduced globally: May 23, 2024**

**Mechanism:**
- Meta limits the number of marketing template messages a given WhatsApp user can receive across **all businesses combined** within a 24-hour rolling window
- The cap is **approximately 2 marketing messages per user per 24-hour period** from all businesses combined — not per sender
- If a user has already received 2 marketing messages today (from any combination of businesses), your message to that user **will fail silently** with **error code 131049**: "This message was not delivered to maintain a healthy ecosystem"
- User engagement (replying to a message) unlocks additional marketing message delivery: one additional message per user reply received
- The cap is dynamic — Meta has not published a fixed hard number; "approximately 2" is the widely observed threshold but it varies by user engagement profile

**What is exempt from the cap:**
- Utility templates (order confirmations, delivery updates, appointment reminders)
- Authentication templates (OTPs, verification codes)
- Free-form session messages within an open 24-hour conversation window
- Click-to-WhatsApp ad conversations

**Practical implication:** For daily restaurant specials, if a customer has already received marketing messages from other businesses that day, your message may not be delivered even with a freshly approved template. Delivery rates for morning sends may be higher than evening sends due to this cap. **UNVERIFIED:** whether time-of-day materially affects cap fill rate.

### 5.2 Opt-In Requirements (Mandatory — Global Policy)
From the WhatsApp Business Policy (binding on all API users):

1. **Prior explicit opt-in required** before sending any marketing template message
2. Opt-in must clearly identify that the recipient will receive WhatsApp messages **from your specific business**
3. The opt-in mechanism must comply with applicable local laws
4. Opt-in must be stored and auditable
5. Separate opt-in per message category is best practice (reduces block/report risk)

### 5.3 Opt-Out Requirements (Mandatory — Global Policy)
From the WhatsApp Business Policy:

> "You must respect all requests...by a person to block, discontinue, or otherwise opt out of communications from you via WhatsApp, including removing that person from your contacts list."

Requirements:
- Every marketing template **must include a clear opt-out mechanism** — typically a Quick Reply button ("Stop", "Unsubscribe") or footer instruction ("Reply STOP to unsubscribe")
- Opt-out requests must be **honoured immediately**; the customer must be removed from the contact list
- Ignoring opt-outs is a policy violation and a primary driver of spam reports and quality degradation

### 5.4 UAE-Specific Rules

#### Meta Platform-Level (Global Policy Applies in UAE)
- No UAE-specific exemptions or additional requirements documented in Meta's policy
- Alcohol promotion in UAE requires confirmation of country eligibility under Meta's Commerce Policy (see Section 1.2)
- UAE rate changes: Meta updated marketing conversation rates for UAE effective October 1, 2024 — not a content rule, but a billing consideration

#### UAE Cabinet Decision No. 56/2024 (Telemarketing Law — Effective August 27, 2024)
This national law applies to marketing messages "sent through social media applications" — WhatsApp falls within scope:

| Requirement | Detail |
|---|---|
| **TDRA prior approval** | Businesses must obtain approval from the Telecommunications and Digital Governance Regulatory Authority (TDRA) before conducting telemarketing via WhatsApp |
| **Operating hours** | Marketing messages should be sent between **9:00 AM – 6:00 PM** UAE local time |
| **Do Not Contact Register (DNCR)** | Businesses must screen against the TDRA DNCR before sending |
| **Business identity disclosure** | Company name and purpose must be clear in all messages |
| **Record-keeping** | All marketing activity and customer database sources must be recorded and available on request |
| **Penalties** | AED 10,000–150,000 fines, activity suspension, licence revocation for repeat violations |

> **Important:** The UAE telemarketing law **explicitly covers social media app messages** (including WhatsApp). Restaurants operating in the UAE using this platform must obtain TDRA approval and comply with operating hours, DNCR screening, and record-keeping obligations. This is **in addition to** Meta's own opt-in/opt-out requirements.

**UNVERIFIED:** Whether TDRA enforcement has been actively applied to WhatsApp API businesses as of mid-2026. Legal counsel review recommended.

---

## 6. AI Generator Best-Practice Checklist for First-Pass Approval

**Sources:** Cross-referenced from all sources above, plus:
- [Infobip Template Compliance Best Practices](https://www.infobip.com/docs/whatsapp/compliance/template-compliance)
- [chakrahq.com — Template Rejection Guidelines](https://chakrahq.com/article/whatsapp-api-template-rejections-issues-guidelines-coexistence/)
- [WUSeller Template Format Rules 2025](https://www.wuseller.com/blog/whatsapp-marketing-template-format-rules-in-2025-with-ready-to-use-examples/)

### Pre-Submission Checklist (AI Generator Must Enforce)

**Naming**
- [ ] Template name uses only lowercase letters, numbers, underscores — no spaces or special characters
- [ ] Template name is unique and has **not been used in the last 30 days** (maintain a name history log)
- [ ] Naming convention example: `daily_special_YYYYMMDD` (ensures uniqueness and auditability)

**Variables / Parameters**
- [ ] All variables use `{{1}}`, `{{2}}` double-curly-bracket syntax with sequential numbering starting at 1
- [ ] No variable numbers are skipped; no variable is repeated
- [ ] Variables are not placed immediately adjacent to each other without intervening static text
- [ ] Static text constitutes the **majority** of the message body (variables are not the primary content)
- [ ] Example/sample values are provided for every variable at submission time

**Header Image (when used)**
- [ ] Image format: JPEG or PNG
- [ ] File size: under 5 MB
- [ ] Aspect ratio: 1.91:1 recommended (800 × 418 px or 1024 × 512 px)
- [ ] Image content: food photography, clean product shot — no alcohol/tobacco imagery, no adult content
- [ ] Text overlay: minimal (brand name only at most); do **not** overlay promotional text, pricing, or fake-urgency phrases on the image
- [ ] No gambling, firearms, or other prohibited content visible in the image

**Body Text**
- [ ] Total body length: under **1,024 characters** (including variable placeholders)
- [ ] Aim for under 5 lines of text (avoid auto-truncation introduced October 2024)
- [ ] No more than 2 consecutive newlines; no more than 4 consecutive spaces
- [ ] Correct spelling and grammar (native-language review or grammar check before submission)
- [ ] No shortened/redirect URLs (bit.ly, tinyurl, etc.) — use full `https://` domain URLs only
- [ ] URLs match the business's registered domain
- [ ] Avoid high-rejection trigger phrases: "100% free", "Win now", "Limited time!!!", excessive exclamation marks
- [ ] Category matches content: if the message is purely promotional (not triggered by customer action), submit as **Marketing** — do not attempt to submit as Utility to save cost; post-April 2025, Meta auto-reclassifies anyway
- [ ] Language code declared matches the actual language of the message content

**Footer**
- [ ] Footer length: under **60 characters**
- [ ] No emojis in footer
- [ ] No URLs or contact information in footer
- [ ] Include opt-out instruction: e.g., "Reply STOP to unsubscribe"

**Buttons**
- [ ] Total buttons: 10 or fewer
- [ ] URL buttons: 2 or fewer; include full `https://` URL; no shortened links
- [ ] Quick reply button text: 25 characters or fewer
- [ ] Include at least one opt-out mechanism (Quick Reply "Stop" or "Unsubscribe")

**Policy**
- [ ] Message is only sent to users who have given explicit opt-in consent for marketing messages from this specific business
- [ ] UAE: message send time is between 9:00 AM – 6:00 PM UAE local time
- [ ] UAE: recipient phone numbers are screened against TDRA DNCR before sending
- [ ] Alcohol content: omit or verify UAE eligibility before including

**Content (Prohibited Categories Check)**
- [ ] No references to gambling, drugs, firearms, tobacco, adult services
- [ ] No claims or guarantees that are false or misleading
- [ ] No impersonation of Meta, WhatsApp, or other brands
- [ ] No request for sensitive personal/financial data
- [ ] No political content

---

## Appendix A: Key Constraints Summary for Daily Create-Delete Design

| Constraint | Value | Source |
|---|---|---|
| Template name reuse blackout after deletion | **30 days** | Meta Developers Documentation |
| Template creation rate limit | **100 templates/hour per WABA** | Meta Developers Documentation |
| Template count — unverified portfolio | **250 per WABA** | Meta Developers Documentation |
| Template count — verified portfolio | **6,000 per WABA** | Meta Developers Documentation |
| Automated approval time (clean template) | **1–30 minutes** | Wati, Twilio, Zoko BSP documentation |
| Manual review time | **Up to 48 hours** | Meta / BSP documentation |
| Per-user marketing frequency cap | **~2 per 24 hours across all businesses** | Meta Developers (error code 131049) — introduced May 23, 2024 |
| Frequency cap error code | **131049** | Meta Cloud API |
| Template pacing (new/restarted templates) | Applies for up to 7 days if prior pauses on phone number | InsideOne Academy |
| Pause escalation: first low quality | **3-hour pause** | Cunnekt, InsideOne |
| Pause escalation: second low quality | **6-hour pause** | Cunnekt, InsideOne |
| Pause escalation: third low quality | **Permanent disable** | Cunnekt, InsideOne |
| Template auto-archival (inactive) | **12 months** | Meta Developers |
| UAE marketing window | **9:00 AM – 6:00 PM** | UAE Cabinet Decision 56/2024 |

---

## Appendix B: Sources Index

1. [WhatsApp Business Policy](https://whatsappbusiness.com/policy/)
2. [Meta Developers — Template Fundamentals](https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/overview)
3. [Meta Developers — Per-User Marketing Template Message Limits](https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/marketing-templates/per-user-limits/)
4. [Meta Developers — Capacity, Quality Rating, Messaging Limits](https://developers.facebook.com/docs/whatsapp/messaging-limits/)
5. [Meta Developers — Template Management](https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/template-management/)
6. [Infobip — WhatsApp Template Compliance](https://www.infobip.com/docs/whatsapp/compliance/template-compliance)
7. [Infobip — WhatsApp Frequency Capping Explained](https://www.infobip.com/blog/what-is-whatsapp-frequency-capping)
8. [8x8 Developer Portal — Template Components Reference](https://developer.8x8.com/connect/docs/whatsapp/template-components-reference/)
9. [Turn.io — Per-User Marketing Template Limits](https://learn.turn.io/l/en/article/kl493nec0m-understanding-whats-app-s-per-user-marketing-template-message-limit)
10. [AiSensy — Frequency Capping Guide](https://m.aisensy.com/blog/meta-frequency-capping-for-whatsapp-marketing-messages/)
11. [AiSensy — Template Approval Process](https://m.aisensy.com/blog/whatsapp-template-approval-process/)
12. [Chatarmin — WhatsApp Messaging Limits 2026](https://chatarmin.com/en/blog/whats-app-messaging-limits)
13. [Cunnekt — Template Quality Rating](https://www.cunnekt.com/blog/whatsapp-template-quality-rating/)
14. [InsideOne Academy — Template Pacing and Pausing](https://academy.insiderone.com/docs/whatsapp-template-pacing-and-pausing)
15. [a2c.chat — Template Rejection Analysis](https://www.a2c.chat/en/whatsapp-template-message-review-guide-5-rejection-reasons-analysis.html)
16. [chakrahq.com — Template Rejection Issues](https://chakrahq.com/article/whatsapp-api-template-rejections-issues-guidelines-coexistence/)
17. [Wati — Meta Template Approval Updates (April 2025)](https://support.wati.io/en/articles/12320234-understanding-meta-s-latest-updates-on-template-approval)
18. [WUSeller — Marketing Template Format Rules 2025](https://www.wuseller.com/blog/whatsapp-marketing-template-format-rules-in-2025-with-ready-to-use-examples/)
19. [Morgan Lewis — UAE Telemarketing Regulations 2024](https://www.morganlewis.com/blogs/sourcingatmorganlewis/2024/07/telemarketing-in-an-evolving-legal-landscape-uae-adopts-regulations-on-telemarketing-activities)
20. [UAE Cabinet Decision No. 56/2024 — Telemarketing Regulations](https://uaelegislation.gov.ae/en/legislations/2519/download)
21. [Vonage — Per-User Marketing Template Messaging Limits](https://api.support.vonage.com/hc/en-us/articles/17270698783516-WhatsApp-Per-User-Marketing-Template-Messaging-Limits)
