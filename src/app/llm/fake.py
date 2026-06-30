from app.llm.port import ConversationAgentResult, DishDraft, UploadedFile

_DEFAULT = [
    DishDraft(
        dish_number=110,
        name="Chicken Biryani",
        price_aed="22.00",
        category="Rice",
        description="Fragrant basmati rice with spiced chicken",
    ),
    DishDraft(
        dish_number=111,
        name="Special Chicken Biryani",
        price_aed="28.00",
        category="Rice",
        description="Premium cut chicken, saffron rice",
    ),
    DishDraft(
        dish_number=201,
        name="Mutton Karahi",
        price_aed="35.00",
        category="Curries",
        description=None,
    ),
]


class FakeExtractor:
    def __init__(self, canned: list[DishDraft] | None = None):
        self._canned = canned

    async def extract_menu(self, files: list[UploadedFile]) -> list[DishDraft]:
        return list(self._canned) if self._canned is not None else list(_DEFAULT)


class FakeDescriber:
    """Test double: returns a deterministic 1-line description, never includes price."""

    def describe(self, name: str, raw_description: str, price_hint: str | None = None) -> str:
        # Truncate raw description to 80 chars; strip price-like patterns
        import re
        safe = re.sub(r"\b(?:AED|aed|\d+\.\d{2})\b", "", raw_description).strip()
        # Spec: max 3 lines — enforce like the production describer
        return "\n".join(f"{name}. {safe[:80]}".splitlines()[:3])


class FakeIntentClassifier:
    """Test double: rule-based classification for known test phrases."""

    _RULES = [
        ({"cancel"}, "cancel"),
        ({"modify", "change"}, "modify"),
        ({"where", "status", "order"}, "status"),
        ({"what is", "describe", "tell me about"}, "dish_question"),
        ({"want", "order", "add", "get"}, "order_item"),
    ]

    def classify(self, text: str) -> str:
        lower = text.lower()
        for keywords, intent in self._RULES:
            if any(k in lower for k in keywords):
                return intent
        return "other"


class FakeArbiter:
    """Test double: always returns the first candidate (deterministic)."""

    async def arbitrate(self, query: str, candidates: list) -> object | None:
        return candidates[0] if candidates else None


class FakeForecastAdjuster:
    """Rule-based ForecastAdjuster test double — no network.

    Scans plain-English override text and emits the parsed_effect DSL.
    Returns ``{}`` when nothing recognisable is found.
    """

    _WEEKDAYS = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    _HORIZONS = ("breakfast", "lunch", "dinner", "midnight", "morning", "evening")

    def parse_override(self, text: str) -> dict:
        import re

        lower = text.lower()
        effect: dict = {}

        for word, dow in self._WEEKDAYS.items():
            if word in lower:
                effect["dow"] = dow
                break

        for horizon in self._HORIZONS:
            if horizon in lower:
                effect["horizon"] = horizon
                break

        if "double" in lower or "twice" in lower:
            effect["order_count_mult"] = 2.0

        # First integer near an order/extra cue -> order_count_delta.
        if re.search(r"\b(extra|more|order|orders)\b", lower):
            match = re.search(r"\b(\d+)\b", lower)
            if match:
                effect["order_count_delta"] = int(match.group(1))

        return effect


class FakeConversationAgent:
    """Test double — returns deterministic responses based on last user message."""

    async def respond(
        self,
        *,
        restaurant_name: str,
        dialogue_phase: str,
        history: list[dict],
        context: dict,
    ) -> "ConversationAgentResult":
        import re

        last_user = ""
        for msg in reversed(history):
            if msg.get("role") == "user":
                last_user = (msg.get("content") or "").lower()
                break
        # Unify curly/smart apostrophes so "that's all" == "that's all".
        last_user = last_user.replace("’", "'").replace("ʼ", "'")

        # ordering phase
        if dialogue_phase == "ordering":
            if "menu" in last_user or "what do you have" in last_user:
                return ConversationAgentResult(
                    message="Here's our menu! 😊", action="show_menu", action_data={},
                )
            # Closing / decline / impatience with a non-empty cart -> proceed.
            # Test double only; real comprehension is DeepSeek's job.
            _closing_tokens = (
                "done", "that's all", "thats all", "bas", "khalaas", "khalas",
                "proceed", "checkout", "no more", "nothing else", "nope",
            )
            _cart = (context.get("cart_summary") or "").strip()
            _is_decline = last_user.strip() in {"no", "na", "nah", "np"}
            if _cart and (_is_decline or any(w in last_user for w in _closing_tokens)):
                return ConversationAgentResult(
                    message="Great! Let me get your delivery details.",
                    action="proceed_to_address",
                    action_data={},
                )
            if any(w in last_user for w in ("cancel",)):
                return ConversationAgentResult(
                    message="Order cancelled.",
                    action="cancel_order",
                    action_data={},
                )
            # Empty the whole cart: "clear the cart", "start over", "remove everything".
            if ("clear" in last_user and "cart" in last_user) or \
                    any(p in last_user for p in ("start over", "remove everything",
                                                 "empty my cart", "empty cart", "delete all")):
                return ConversationAgentResult(
                    message="Cleared!", action="clear_cart", action_data={},
                )
            # Multi-dish quantity change ("make it 2 X and 3 Y") → update_qty items.
            # Checked BEFORE the multi-dish add split so a "make it" stays an update.
            if any(p in last_user for p in ("make it", "change", "update", "set to")) and \
                    re.search(r",|\band\b|\+", last_user):
                clauses = re.split(r"\s*(?:,|\band\b|\+)\s*", last_user)
                ups = []
                for clause in clauses:
                    clause = re.sub(r"\b(make it|change|update to|update|set to|set|to)\b", " ", clause).strip()
                    m = re.match(r"^(\d+)\s*[xX]?\s+(.*)$", clause)
                    if m and m.group(2).strip():
                        ups.append({"dish_query": m.group(2).strip(), "qty": int(m.group(1))})
                if len(ups) >= 2:
                    return ConversationAgentResult(
                        message="Updated!", action="update_qty", action_data={"items": ups},
                    )
            # Parse quantity prefix: "2x biryani" or "2 biryani"
            qty = 1
            dish_query = last_user
            qty_match = re.match(r'^(\d+)\s*[xX]\s+', last_user)
            if qty_match:
                qty = int(qty_match.group(1))
                dish_query = last_user[qty_match.end():]
            # Greeting → no_action; use word-set to avoid "hi" matching "chicken"
            _last_words = set(re.findall(r'\b\w+\b', last_user))
            if _last_words & {"hi", "hello", "hey", "salam", "salaam"}:
                return ConversationAgentResult(
                    message=context.get("menu_text", "Welcome! Here is our menu."),
                    action="no_action",
                    action_data={},
                )
            # Status query detection
            if any(w in last_user for w in ("where", "status", "track", "eta", "when")):
                return ConversationAgentResult(
                    message="Let me check your order status.",
                    action="status_query",
                    action_data={},
                )
            # Multi-dish message: split on commas / "and" / "+" and emit one item per
            # clause so the engine adds them ALL (mirrors the real agent's 'items').
            if re.search(r",|\band\b|\+", last_user):
                clauses = re.split(r"\s*(?:,|\band\b|\+)\s*", last_user)
                parsed = []
                for clause in clauses:
                    clause = clause.strip()
                    if not clause:
                        continue
                    cqty = 1
                    m = re.match(r'^(\d+)\s*[xX]?\s+(.*)$', clause)
                    if m:
                        cqty = int(m.group(1))
                        clause = m.group(2).strip()
                    if clause:
                        parsed.append({"dish_query": clause, "qty": cqty, "special_note": ""})
                if len(parsed) >= 2:
                    return ConversationAgentResult(
                        message="Got it! Added everything to your cart 🛒",
                        action="add_item",
                        action_data={"items": parsed},
                    )
            # Any non-empty text → try add_item; engine will send no-match if dish not found
            if last_user:
                return ConversationAgentResult(
                    message=f"Added {dish_query} to your cart! 🛒",
                    action="add_item",
                    action_data={"dish_query": dish_query, "qty": qty, "special_note": ""},
                )
            return ConversationAgentResult(
                message=context.get("menu_text", "Welcome! Here is our menu."),
                action="no_action",
                action_data={},
            )

        # address_capture phase
        if dialogue_phase == "address_capture":
            saved = context.get("saved_address", "")
            location_received = context.get("location_received", False)
            # Location received + saved address → offer the saved address
            if saved and location_received:
                return ConversationAgentResult(
                    message=f"I see your saved address: {saved}. Would you like to use it?",
                    action="no_action",
                    action_data={},
                )
            if saved and any(w in last_user for w in ("yes", "same", "correct", "ok")):
                return ConversationAgentResult(
                    message="Using your saved address!",
                    action="use_saved_address",
                    action_data={},
                )
            if not location_received:
                return ConversationAgentResult(
                    message="Please share your location 📍",
                    action="send_location_request",
                    action_data={},
                )
            apt = context.get("apt_room", "")
            building = context.get("building", "")
            if apt and building:
                return ConversationAgentResult(
                    message="Got it! What's the receiver's name?",
                    action="no_action",
                    action_data={},
                )
            return ConversationAgentResult(
                message="Please share your room/apartment number and building name.",
                action="no_action",
                action_data={},
            )

        # awaiting_confirmation phase
        if dialogue_phase == "awaiting_confirmation":
            if any(w in last_user for w in ("yes", "confirm", "ok", "proceed", "haan", "aiwa")):
                return ConversationAgentResult(
                    message="Order confirmed! 🎉",
                    action="confirm_order",
                    action_data={},
                )
            if any(w in last_user for w in ("cancel",)):
                return ConversationAgentResult(
                    message="Order cancelled.",
                    action="cancel_order",
                    action_data={},
                )
            # Confirm-step edits — add/remove a dish or change a quantity.
            if "add" in last_user:
                dish = last_user.split("add", 1)[1].strip()
                return ConversationAgentResult(
                    message="Sure, adding that.", action="add_item",
                    action_data={"dish_query": dish, "qty": 1, "special_note": ""},
                )
            if "remove" in last_user:
                dish = last_user.split("remove", 1)[1].strip()
                return ConversationAgentResult(
                    message="Sure, removing that.", action="remove_item",
                    action_data={"dish_query": dish, "qty": None},
                )
            return ConversationAgentResult(
                message="Please confirm or cancel your order.",
                action="no_action",
                action_data={},
            )

        # post_order phase
        if dialogue_phase == "post_order":
            if any(w in last_user for w in ("cancel",)):
                return ConversationAgentResult(
                    message="Order cancelled.",
                    action="cancel_order",
                    action_data={},
                )
            if any(w in last_user for w in ("modify", "change", "update", "edit")):
                return ConversationAgentResult(
                    message="Sure! Let me help you modify your order.",
                    action="request_modification",
                    action_data={},
                )
            return ConversationAgentResult(
                message="Your order is being prepared! 🛵",
                action="status_query",
                action_data={},
            )

        return ConversationAgentResult(
            message="How can I help?",
            action="no_action",
            action_data={},
        )


class FakeSegmentCompiler:
    """Test double: rule-based plain-English -> validated segment DSL.

    Heuristics (spec §4.7): "spend/aed + number" -> total_spend gte; "vip"/tag
    words -> tag contains; "last N days" -> last_order_days_ago lte N. Emits a
    top-level "all" tree; the service still calls ``validate_dsl`` before use.
    """

    def compile(self, text: str) -> dict:
        import re

        lower = text.lower()
        conditions: list[dict] = []

        spend = re.search(r"(?:spen\w*|aed|dirham\w*)\D*(\d+)", lower)
        if not spend:
            spend = re.search(r"(\d+)\s*(?:aed|dirham)", lower)
        if spend:
            conditions.append(
                {"field": "total_spend", "op": "gte", "value": int(spend.group(1))}
            )

        days = re.search(r"last\s+(\d+)\s*days?", lower)
        if days:
            conditions.append(
                {"field": "last_order_days_ago", "op": "lte", "value": int(days.group(1))}
            )

        for tag in ("vip", "regular", "loyal"):
            if tag in lower:
                conditions.append({"field": "tag", "op": "contains", "value": tag})

        if not conditions:
            # Fall back to a benign tag match so output always validates.
            conditions.append({"field": "tag", "op": "contains", "value": "all"})

        return {"all": conditions}
