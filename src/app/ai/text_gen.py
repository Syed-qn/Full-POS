"""Deterministic AI narrative generator + optional LLM hook.

Tests and offline always use FakeNarrative so features are fully wired without
external API keys. When ``APP_LLM_PROVIDER`` is claude/deepseek, real models can
polish summaries (best-effort, never required).
"""

from __future__ import annotations

from typing import Any


def fake_narrative(kind: str, facts: dict[str, Any]) -> str:
    """Deterministic, grounded prose from structured facts only."""
    if kind == "daily_sales":
        return (
            f"Sales recap for {facts.get('date')}: "
            f"{facts.get('order_count', 0)} orders, "
            f"AED {facts.get('gross_aed', '0')} gross "
            f"(net AED {facts.get('net_aed', '0')}, VAT AED {facts.get('vat_aed', '0')}). "
            f"Top dish: {facts.get('top_dish') or 'n/a'}. "
            f"Channel mix: {facts.get('channel_note') or 'native only'}."
        )
    if kind == "sales_drop":
        drop = facts.get("drop_pct", 0)
        drivers = facts.get("drivers") or ["volume lower than prior period"]
        return (
            f"Sales are down ~{drop}% vs prior period "
            f"(AED {facts.get('current_gross')} vs AED {facts.get('prior_gross')}). "
            f"Likely drivers: {'; '.join(drivers)}. "
            f"Suggested focus: {facts.get('suggestion') or 'review traffic and top SKUs'}."
        )
    if kind == "staff_summary":
        return (
            f"Staff performance ({facts.get('period')}): "
            f"{facts.get('staff_count', 0)} active. "
            f"Top seller: {facts.get('top_seller') or 'n/a'} "
            f"(AED {facts.get('top_sales', '0')}). "
            f"Mistakes logged: {facts.get('mistake_count', 0)}. "
            f"{facts.get('note') or 'Keep coaching on void/discount discipline.'}"
        )
    if kind == "food_cost_anomaly":
        return (
            f"Food-cost anomaly on {facts.get('dish_name') or 'item'}: "
            f"theoretical cost {facts.get('theo_pct')}% of price "
            f"(threshold {facts.get('threshold_pct')}%). "
            f"{facts.get('note') or 'Check recipe yield and ingredient costs.'}"
        )
    if kind == "slow_moving":
        items = facts.get("items") or []
        names = ", ".join(i.get("name", "?") for i in items[:5]) or "none"
        return f"Slow-moving items (low sales last {facts.get('days', 14)} days): {names}."
    if kind == "low_stock":
        items = facts.get("items") or []
        names = ", ".join(
            f"{i.get('name')} ({i.get('on_hand')}/{i.get('par')})" for i in items[:5]
        ) or "none critical"
        return (
            f"Stock risk (demand-aware): {names}. "
            f"{facts.get('note') or 'Reorder or 86 before peak.'}"
        )
    if kind == "segment_label":
        return (
            f"Segment '{facts.get('key')}': {facts.get('count', 0)} customers. "
            f"{facts.get('playbook') or 'Target with matching offer.'}"
        )
    if kind == "upsell":
        return (
            f"Customers who ordered {facts.get('trigger') or 'this'} often add "
            f"{facts.get('suggest') or 'a side'}. "
            f"{facts.get('reason') or 'Strong co-purchase signal.'}"
        )
    if kind == "combo":
        return (
            f"Bundle suggestion: {facts.get('bundle') or 'combo'}. "
            f"{facts.get('reason') or 'Frequent together; good AOV lift.'}"
        )
    if kind == "reorder":
        return (
            f"Hi {{{{1}}}}, ready for your usual "
            f"{facts.get('habit_dish') or 'order'}? "
            f"Reply anytime and we'll fire it up 🍽️"
        )
    if kind == "abandoned":
        cart = facts.get("cart") or "your items"
        return (
            f"Hi 👋 You still have items in your cart:\n\n🛒 {cart}\n\n"
            "Say *done* whenever you're ready to check out, "
            "or tell me anything else you'd like to add 😊"
        )
    if kind == "review_reply":
        score = facts.get("score")
        if score is not None and int(score) <= 6:
            return (
                f"We're truly sorry about your experience"
                f"{' — ' + facts.get('theme') if facts.get('theme') else ''}. "
                "A manager will follow up shortly. Thank you for the feedback."
            )
        return (
            f"Thank you for the kind words"
            f"{' about ' + facts.get('theme') if facts.get('theme') else ''}! "
            "We hope to serve you again soon."
        )
    if kind == "eta_explain":
        return (
            f"Estimated delivery ~{facts.get('eta_min', 40)} min: "
            f"{facts.get('prep_min', 15)} min kitchen + "
            f"{facts.get('drive_min', 20)} min road"
            f"{' (batched with nearby orders)' if facts.get('batched') else ''}. "
            f"{facts.get('extra') or ''}".strip()
        )
    if kind == "festival":
        return (
            f"{facts.get('festival') or 'Festival'} campaign draft: "
            f"{facts.get('hook') or 'Celebrate with us!'} "
            f"Offer: {facts.get('offer') or 'special set menu'}. "
            f"Channels: WhatsApp + in-app. CTA: order now."
        )
    if kind == "promotion":
        return (
            f"Hi {{{{1}}}}, {facts.get('describe') or 'special offer'}. "
            "Reply to order. See you soon! 🍽️"
        )
    if kind == "reservation":
        return (
            f"Reservation for {facts.get('party_size', 2)} on "
            f"{facts.get('when')}: {facts.get('guest') or 'guest'}. "
            f"{facts.get('notes') or 'No special notes.'}"
        )
    if kind == "call_turn":
        return facts.get("reply") or (
            "Thanks for calling. I can take your order, check status, "
            "or help with a reservation. What would you like?"
        )
    if kind == "translation":
        # Deterministic stub marks Arabic target without inventing fake Arabic script
        # unless a mapping exists; real LLM can replace when configured.
        name = facts.get("name") or ""
        desc = facts.get("description") or ""
        lang = facts.get("target_lang") or "ar"
        return f"[{lang}] {name}" + (f" | {desc}" if desc else "")
    return f"{kind}: {facts}"


async def generate_narrative(kind: str, facts: dict[str, Any]) -> str:
    """Best-effort LLM polish; always falls back to fake_narrative."""
    base = fake_narrative(kind, facts)
    try:
        from app.config import get_settings

        settings = get_settings()
        provider = (settings.llm_provider or "fake").lower()
        if provider in ("fake", "none", ""):
            return base
        # Optional light polish — keep grounded facts in the prompt; if anything
        # fails, return deterministic base so production never blocks.
        prompt = (
            f"Rewrite this restaurant ops insight in 2 short sentences. "
            f"Do not invent numbers. Facts JSON: {facts}\nDraft: {base}"
        )
        if provider == "deepseek" and settings.deepseek_api_key.get_secret_value():
            from app.llm.deepseek import _async_chat, _get_deepseek_settings

            api_key, model = _get_deepseek_settings()
            raw = await _async_chat(
                api_key, model, [{"role": "user", "content": prompt}], max_tokens=200
            )
            return (raw or base).strip() or base
        if provider == "claude" and settings.anthropic_api_key.get_secret_value():
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(api_key=settings.anthropic_api_key.get_secret_value())
            resp = await client.messages.create(
                model=settings.claude_model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text if resp.content else ""
            return (text or base).strip() or base
    except Exception:  # noqa: BLE001
        return base
    return base
