"""Capability eval — RA-7 / F49 / RA-5: biryani correction incident.

A customer sends a catalogue basket (Mndhi-2 ×3, Lemon Mint ×1, Chicken Biryani ×1),
then tries to add a double-masala note, reduce the biryani to 1, and asks a rhetorical
question ("Why did you add 2 biriyani") that MUST NOT mutate the cart.

Today's engine fails: it adds a duplicate biryani line instead of updating the existing
one, strips the note, and re-adds on the rhetorical question turn.

This eval is xfail(strict=True) — it runs end-to-end and FAILS today (reproducing the
incident exactly); W2 (notes), W3 (render), and W4 (router) will flip it to passing.
"""
import json
from pathlib import Path

import pytest

from tests.harness.graders import grade_no_duplicate_dish_line, grade_no_mutation
from tests.harness.replay import drive_turns

FIXTURE = Path(__file__).parent.parent / "fixtures" / "transcripts" / "biryani_r1_0097.json"


@pytest.mark.asyncio
async def test_biryani_correction_final_state(db_session, restaurant, seed_biryani_menu):
    data = json.loads(FIXTURE.read_text())
    res = await drive_turns(
        db_session,
        restaurant_id=restaurant.id,
        phone=data["phone"],
        turns=data["turns"],
    )
    final = res.final_cart()
    # Expected end state: exactly one biryani line, qty 1, note preserved; no duplicate.
    biryani = [r for r in final if "biryani" in r["dish_name"].lower()]
    assert len(biryani) == 1, f"expected one biryani line, got {biryani}"
    assert biryani[0]["qty"] == 1
    assert biryani[0]["notes"] and "double masala" in biryani[0]["notes"].lower()
    # 'Why did you add 2' turn (index 4) must NOT have mutated the cart vs the turn before it.
    assert grade_no_mutation(res.turns[3].cart_rows, res.turns[4]).passed
    assert grade_no_duplicate_dish_line(res.turns[-1]).passed
