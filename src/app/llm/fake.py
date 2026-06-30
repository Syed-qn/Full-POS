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
    """Test double -- returns deterministic responses based on last user message.

    All outputs are routed through ``to_engine_result`` so the returned
    ConversationAgentResult.action is always the engine-legacy action name,
    exactly as the real providers (DeepSeek, Claude) produce.  No branch may
    return a raw action string directly.
    """

    async def respond(
        self,
        *,
        restaurant_name: str,
        dialogue_phase: str,
        history: list[dict],
        context: dict,
    ) -> "ConversationAgentResult":
        import re
        from app.llm.action_schema import to_engine_result

        last_user = ""
        for msg in reversed(history):
            if msg.get("role") == "user":
                last_user = (msg.get("content") or "").lower()
                break
        # Unify curly/smart apostrophes so "that's all" == "that's all".
        last_user = (
            last_user
            .replace("‘", "'")
            .replace("’", "'")
            .replace("ʼ", "'")
            .strip()
        )

        def _emit(canon: str, payload: dict, message: str = "") -> "ConversationAgentResult":
            action, data = to_engine_result(canon, payload, message=message)
            return ConversationAgentResult(message=message, action=action, action_data=data)

        # ordering phase
        if dialogue_phase == "ordering":
            if "menu" in last_user or "what do you have" in last_user:
                return _emit("menu_show", {}, "Here's our menu! 😊")

            _closing = (
                "done", "that's all", "thats all", "bas", "khalaas", "khalas",
                "proceed", "checkout", "no more", "nothing else", "nope",
            )
            _cart = (context.get("cart_summary") or "").strip()
            if last_user in {"no", "na", "nah", "np"} or any(w in last_user for w in _closing):
                if not _cart:
                    return _emit("no_action", {}, "Your cart is empty 😊 What would you like to order?")
                return _emit("checkout_proceed", {}, "Great! Let me get your delivery details.")

            if "cancel" in last_user:
                return _emit("cancel_order", {}, "Order cancelled.")

            if ("clear" in last_user and "cart" in last_user) or any(
                p in last_user for p in ("start over", "remove everything",
                                         "empty my cart", "empty cart", "delete all")):
                return _emit("cart_clear", {}, "Cleared!")

            # Multi-dish set ("make it 2 X and 3 Y").
            if any(p in last_user for p in ("make it", "change", "set to")) and re.search(
                r",|\band\b|\+", last_user
            ):
                clauses = re.split(r"\s*(?:,|\band\b|\+)\s*", last_user)
                ups = []
                for c in clauses:
                    c = re.sub(r"\b(make it|change(?: to)?|set(?: to)?|only)\b", " ", c).strip()
                    mm = re.match(r"^(\d+)\s*[xX]?\s+(.*)$", c)
                    if mm and mm.group(2).strip():
                        ups.append({"op": "set_total", "dish_query": mm.group(2).strip(), "qty": int(mm.group(1))})
                if len(ups) >= 2:
                    return _emit("cart_set_qty", {"items": ups}, "Updated!")

            # Single-dish set: "only N X" / "make it N X" -> cart_set_qty absolute.
            # Checked AFTER multi-dish so "make it 2 X and 3 Y" is not greedily consumed.
            m_set = re.match(
                r"^(?:only|make it|change(?: to)?|set(?: to)?)\s+(\d+)\s*[xX]?\s+(.+)$",
                last_user,
            )
            if m_set and m_set.group(2).strip():
                return _emit(
                    "cart_set_qty",
                    {"dish_query": m_set.group(2).strip(), "new_total": int(m_set.group(1))},
                    "Updated!",
                )

            if "remove" in last_user:
                dish = last_user.split("remove", 1)[1].strip()
                if dish:
                    return _emit("cart_remove", {"dish_query": dish}, "Sure, removing that.")

            if {"hi", "hello", "hey", "salam", "salaam"} & set(re.findall(r"\b\w+\b", last_user)):
                return _emit("no_action", {}, context.get("menu_text", "Welcome! Here is our menu."))

            if any(w in last_user for w in ("where", "status", "track", "eta", "when")):
                return _emit("status_query", {}, "Let me check your order status.")

            # Multi-dish add (delta).
            if re.search(r",|\band\b|\+", last_user):
                clauses = re.split(r"\s*(?:,|\band\b|\+)\s*", last_user)
                parsed = []
                for c in clauses:
                    c = c.strip()
                    if not c:
                        continue
                    cq = 1
                    mm = re.match(r"^(\d+)\s*[xX]?\s+(.*)$", c)
                    if mm:
                        cq, c = int(mm.group(1)), mm.group(2).strip()
                    if c:
                        parsed.append({"op": "add_delta", "dish_query": c, "qty": cq})
                if len(parsed) >= 2:
                    return _emit("cart_add", {"items": parsed}, "Got it! Added everything to your cart 🛒")

            # Single add (delta) -- explicit "N X" or bare dish name.
            qty, dish = 1, last_user
            mq = re.match(r"^(\d+)\s*[xX]?\s+(.*)$", last_user)
            if mq:
                qty, dish = int(mq.group(1)), mq.group(2).strip()
            if dish:
                return _emit("cart_add", {"dish_query": dish, "add_qty": qty},
                             f"Added {dish} to your cart! 🛒")
            return _emit("no_action", {}, context.get("menu_text", "Welcome! Here is our menu."))

        # address_capture phase
        if dialogue_phase == "address_capture":
            saved = context.get("saved_address", "")
            location_received = context.get("location_received", False)
            if saved and location_received:
                return _emit("no_action", {},
                             f"I see your saved address: {saved}. Would you like to use it?")
            if saved and any(w in last_user for w in ("yes", "same", "correct", "ok")):
                return _emit("address_use_saved", {}, "Using your saved address!")
            if not location_received:
                return _emit("address_location", {}, "Please share your location 📍")
            apt = context.get("apt_room", "")
            building = context.get("building", "")
            if apt and building:
                return _emit("no_action", {}, "Got it! What's the receiver's name?")
            return _emit("no_action", {}, "Please share your room/apartment number and building name.")

        # awaiting_confirmation phase
        if dialogue_phase == "awaiting_confirmation":
            if any(w in last_user for w in ("yes", "confirm", "ok", "proceed", "haan", "aiwa")):
                return _emit("confirm_order", {}, "Order confirmed! 🎉")
            if "cancel" in last_user:
                return _emit("cancel_order", {}, "Order cancelled.")
            # Confirm-step edits -- use word-boundary \badd\b to prevent false positives
            # from substrings ("address" contains "add") or negations ("don't add more").
            _add_word = re.search(r"\badd\b", last_user)
            _negated = re.search(r"\b(don'?t|dont|not)\b", last_user)
            if _add_word and not _negated:
                dish = re.split(r"\badd\b", last_user, maxsplit=1)[1].strip()
                return _emit("cart_add", {"dish_query": dish, "add_qty": 1}, "Sure, adding that.")
            if "remove" in last_user:
                dish = last_user.split("remove", 1)[1].strip()
                return _emit("cart_remove", {"dish_query": dish}, "Sure, removing that.")
            return _emit("no_action", {}, "Please confirm or cancel your order.")

        # post_order phase
        if dialogue_phase == "post_order":
            if "cancel" in last_user:
                return _emit("cancel_order", {}, "Order cancelled.")
            if any(w in last_user for w in ("modify", "change", "update", "edit")):
                return _emit("request_modification", {}, "Sure! Let me help you modify your order.")
            return _emit("status_query", {}, "Your order is being prepared! 🛵")

        return _emit("no_action", {}, "How can I help?")


class FakeCompletionDetector:
    """Test double: deterministic completion-intent detector.

    Normalises curly/smart apostrophes, then checks whether the lowercased
    text matches a known multilingual closing-token set.  Returns False for
    empty/blank input, dish names, and questions.
    """

    # Token set mirrors FakeConversationAgent's closing logic + spec token list.
    _COMPLETION_TOKENS = frozenset({
        "done", "that's all", "thats all", "checkout", "proceed",
        "finish", "no more", "nothing else",
        # Arabic / Gulf
        "bas", "khalas", "khalaas", "khallas",
        # Bare declines that signal "I'm done, move on"
        "no", "na", "nah", "np", "nope",
    })

    def _normalise(self, text: str) -> str:
        # Unify curly / smart / modifier apostrophes → straight apostrophe.
        return (
            text
            .replace("’", "'")   # RIGHT SINGLE QUOTATION MARK
            .replace("‘", "'")   # LEFT SINGLE QUOTATION MARK
            .replace("ʼ", "'")   # MODIFIER LETTER APOSTROPHE
        )

    async def is_completion(self, text: str) -> bool:
        if not text or not text.strip():
            return False
        normalised = self._normalise(text).lower().strip()
        # Bare token match (exact).
        if normalised in self._COMPLETION_TOKENS:
            return True
        # Contains-match: a completion token appears as a sub-phrase (e.g. "no that's all").
        for token in self._COMPLETION_TOKENS:
            # Only multi-word tokens are safe to match as substrings; single
            # words like "no" / "na" must be exact to avoid false positives
            # (e.g. "no onion" contains "no" but is an item instruction).
            if " " in token and token in normalised:
                return True
        return False


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
