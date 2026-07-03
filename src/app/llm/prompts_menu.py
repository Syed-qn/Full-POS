"""Menu, dish, segment, and forecast auxiliary prompts.

Non-conversation LLM tasks: extraction, descriptions, arbitration, legacy intent,
segment DSL compilation, and forecast override parsing.
"""

EXTRACT_SYSTEM = """\
[ROLE]
You are a menu digitization assistant for restaurant menus.

[TASK]
Extract every dish from the provided menu content.

[CONSTRAINTS]
- Do not invent dishes, item numbers, or prices.
- Preserve original spelling of dish names.
- dish_number: integer when printed, otherwise null
- name: required string
- price_aed: decimal string when shown, otherwise null
- category: section heading when present, otherwise null
- description: printed text when present, otherwise null
- variants: when a dish lists MULTIPLE prices for different sizes/portions
  (e.g. "19/30/50" or "60 / 80", or a Small/Medium/Large row), set price_aed to
  the smallest/first price and put EACH larger size in variants as
  {"name": "<size>", "price_aed": "<price>"}. Use the printed size names when
  shown; otherwise use Small/Medium/Large (or Regular/Large for two prices).
  Never put a slash-joined value like "19/30/50" in price_aed.

[OUTPUT]
A JSON array of dish objects only. No prose, no markdown fences.
"""

DESCRIBE_DISH_TEMPLATE = """\
[ROLE]
You write customer-facing restaurant dish descriptions.

[TASK]
Write a short description for the dish below.

[INPUT]
Name: {name}
Details: {raw_description}

[CONSTRAINTS]
- Maximum 3 lines.
- No price, currency amounts, or "AED".
- Factual and appetising.

[OUTPUT]
Plain text description only.
"""

ARBITRATE_TEMPLATE = """\
[ROLE]
You match customer dish queries to menu items.

[TASK]
Pick the best matching menu item for the customer's query.

[INPUT]
Customer typed: {query!r}
Candidates:
{options}

[CONSTRAINTS]
- Choose the single best match by number.
- Reply 0 if none match.

[OUTPUT]
One integer: the candidate number (1-{candidate_count}), or 0.
"""

INTENT_CLASSIFY_TEMPLATE = """\
[ROLE]
You classify WhatsApp messages from restaurant customers.

[TASK]
Assign exactly one intent label to the message.

[INPUT]
Message: {text!r}

[CONSTRAINTS]
Valid labels only: order_item, dish_question, cancel, modify, status, other

[OUTPUT]
Exactly one label word.
"""

SEGMENT_COMPILE_TEMPLATE = """\
[ROLE]
You translate audience descriptions into segment filter DSL for a restaurant CRM.

[TASK]
Convert the manager's plain-English audience description into segment DSL JSON.

[INPUT]
Description: {text!r}

[CONSTRAINTS]
- Schema: top-level key "all" (AND) or "any" (OR) → list of conditions.
- Each condition: {{"field":..,"op":..,"value":..}}
- Allowed fields/ops:
  total_spend: eq|gte|lte|gt|lt (numeric AED)
  order_count: eq|gte|lte|gt|lt (integer)
  last_order_days_ago: eq|gte|lte|gt|lt (integer days)
  tag: contains (string)
  ordered_dish_id: eq (integer dish id)
- Use only these fields and ops.

[OUTPUT]
JSON object only. No prose, no markdown fences.
"""

FORECAST_OVERRIDE_TEMPLATE = """\
[ROLE]
You parse restaurant forecast overrides from manager notes.

[TASK]
Convert the manager's plain-English note into a forecast effect JSON object.

[INPUT]
Manager note: {text!r}

[CONSTRAINTS]
Include only these optional keys:
- horizon: breakfast|lunch|dinner|midnight|morning|evening, or null
- dow: integer 0-6 (Monday=0 .. Sunday=6), or null
- order_count_delta: integer (default 0)
- order_count_mult: float (default 1.0)
- revenue_mult: float (default 1.0)
- dish_demand_delta: object mapping dish_id string → integer
Omit keys you cannot infer.

[OUTPUT]
JSON object only. No prose, no markdown fences.
"""