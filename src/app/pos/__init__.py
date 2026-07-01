"""External POS integration (e.g. Cratis).

Self-contained module that pulls a restaurant's menu from its POS endpoint and mirrors
it into the dishes table (so it flows to the WhatsApp catalogue via the existing Meta
publish pipeline). Kept entirely separate from the manual menu-management flows in
``app.menu`` — it only ever touches dishes it owns (tagged with ``pos_product_id``).
"""
