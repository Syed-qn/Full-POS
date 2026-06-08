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
    """Test double: rule-based conversation agent, no network."""

    async def respond(
        self,
        *,
        restaurant_name: str,
        menu_text: str,
        history: list[dict],
        cart_summary: str,
    ) -> ConversationAgentResult:
        last_user = ""
        for msg in reversed(history):
            if msg.get("role") == "user":
                last_user = msg.get("content", "").lower()
                break
        if any(w in last_user for w in ("done", "checkout", "that's all", "thats all")):
            return ConversationAgentResult(
                message="Got it! Moving to delivery details.",
                action="proceed_checkout",
                action_data={},
            )
        if any(w in last_user for w in ("cancel", "never mind", "nevermind")):
            return ConversationAgentResult(
                message="Order cancelled. Send 'hi' to start again.",
                action="cancel_cart",
                action_data={},
            )
        # Simple "N item_name" or "item_name" pattern
        import re
        m = re.match(r"^(?:(\d+)\s*x?\s*)?(.+)$", last_user.strip())
        if m:
            qty_str, query = m.group(1), m.group(2).strip()
            qty = int(qty_str) if qty_str else 1
            query_words = set(re.findall(r"\b\w+\b", query))
            _greet_words = {"hi", "hello", "hey", "menu", "start", "hiu", "salam"}
            if query and not query_words.issubset(_greet_words | {"please", "send", "show"}) and not query_words & _greet_words:
                return ConversationAgentResult(
                    message=f"Adding {qty}x {query} to your cart.",
                    action="add_item",
                    action_data={"dish_query": query, "qty": qty},
                )
        return ConversationAgentResult(
            message=f"{menu_text}\n\nReply with a dish name or number to order.",
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
