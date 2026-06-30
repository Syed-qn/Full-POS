from __future__ import annotations
from dataclasses import dataclass


@dataclass
class GradeResult:
    passed: bool
    reason: str


def grade_no_duplicate_dish_line(turn) -> GradeResult:
    seen = set()
    for r in turn.cart_rows:
        key = (r["dish_id"], r.get("variant_name"))
        if key in seen:
            return GradeResult(False, f"duplicate line for {key}")
        seen.add(key)
    return GradeResult(True, "no duplicate lines")


def grade_last_outbound_matches_cart(turn) -> GradeResult:
    if not turn.outbounds:
        return GradeResult(False, "no outbound for a turn with a cart")
    body = turn.outbounds[-1].body.lower()
    missing = [r["dish_name"] for r in turn.cart_rows if r["dish_name"].lower() not in body]
    if missing:
        return GradeResult(False, f"reply omits cart dishes: {missing}")
    return GradeResult(True, "reply names all cart dishes")


def grade_total_consistency(turn) -> GradeResult:
    if turn.total is None or turn.subtotal is None:
        return GradeResult(True, "no totals to check")
    if turn.total < turn.subtotal:
        return GradeResult(False, f"total {turn.total} < subtotal {turn.subtotal}")
    return GradeResult(True, "total >= subtotal")


def _cart_key(cart):
    return sorted((r["dish_id"], r.get("variant_name"), r.get("notes"), r["qty"]) for r in cart)


def grade_no_mutation(prev_cart, turn) -> GradeResult:
    if _cart_key(prev_cart) != _cart_key(turn.cart_rows):
        return GradeResult(False, "cart mutated on a no-mutation turn")
    return GradeResult(True, "cart unchanged")


def grade_reply_subset_of_menu(turn, menu_names) -> GradeResult:
    menu_lower = {n.lower() for n in menu_names}
    for r in turn.cart_rows:  # any named dish in cart must exist on the menu
        if r["dish_name"].lower() not in menu_lower:
            return GradeResult(False, f"cart dish not on menu: {r['dish_name']}")
    return GradeResult(True, "cart dishes are on menu")
