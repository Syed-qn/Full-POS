#!/usr/bin/env python3
"""Enable partner integration on an existing restaurant, pointed at the temp POS.

One-shot setup for local testing: finds the restaurant by phone, turns partner
integration on, points its webhook at scripts/temp_pos.py (127.0.0.1:8799),
sets a shared HMAC secret, and mints an API key — then prints everything you
need to paste into the temp POS.

Run from repo root (uses the local DB from .env APP_DATABASE_URL):
  .venv/Scripts/python scripts/enable_partner_for_test.py +9715XXXXXXXX

Or set the phone via env:
  POS_TEST_PHONE=+9715XXXXXXXX .venv/Scripts/python scripts/enable_partner_for_test.py
"""
from __future__ import annotations

import asyncio
import os
import sys

os.environ.setdefault("APP_LLM_PROVIDER", "fake")

from sqlalchemy import select  # noqa: E402

from app.db import async_session_factory  # noqa: E402
from app.identity.models import Restaurant  # noqa: E402
from app.partner.integration import apply_partner_settings  # noqa: E402
from app.partner.keys import generate_api_key  # noqa: E402
from app.partner.models import PartnerApiKey  # noqa: E402

WEBHOOK_URL = os.environ.get("POS_TEST_WEBHOOK_URL", "http://127.0.0.1:8799/hooks/whatsapp")
WEBHOOK_SECRET = os.environ.get("POS_TEST_WEBHOOK_SECRET", "temp-pos-secret")
POS_STORE_ID = os.environ.get("POS_TEST_STORE_ID", "TEMP-POS-STORE")


async def main(phone: str) -> int:
    async with async_session_factory() as session:
        rest = await session.scalar(select(Restaurant).where(Restaurant.phone == phone))
        if rest is None:
            print(f"No restaurant with phone {phone}. Sign it up first (the number")
            print("your WhatsApp orders route to), then re-run.")
            return 1

        apply_partner_settings(
            rest,
            {
                "partner_enabled": True,
                "partner_webhook_url": WEBHOOK_URL,
                "partner_webhook_secret": WEBHOOK_SECRET,
                "pos_store_id": POS_STORE_ID,
                "pos_order_push_mode": "webhook",
            },
        )

        # Reuse an existing "Temp POS" key or mint a new one.
        existing = await session.scalar(
            select(PartnerApiKey).where(
                PartnerApiKey.restaurant_id == rest.id,
                PartnerApiKey.label == "Temp POS",
                PartnerApiKey.revoked_at.is_(None),
            )
        )
        api_key: str | None = None
        if existing is None:
            full_key, prefix, key_hash = generate_api_key()
            session.add(
                PartnerApiKey(
                    restaurant_id=rest.id,
                    label="Temp POS",
                    key_prefix=prefix,
                    key_hash=key_hash,
                )
            )
            api_key = full_key
        await session.commit()

    print("\n--- Partner enabled for testing ---")
    print(f"Restaurant   : id={rest.id}  phone={phone}")
    print(f"Webhook URL  : {WEBHOOK_URL}")
    print(f"HMAC secret  : {WEBHOOK_SECRET}")
    print(f"POS store id : {POS_STORE_ID}")
    if api_key:
        print(f"API key (ONCE): {api_key}")
    else:
        print("API key      : existing 'Temp POS' key kept (revoke & re-run to mint new)")
    print("\nNow run the temp POS with:")
    key_show = api_key or "<your-existing-key>"
    print(
        f"  POS_BASE_URL=http://127.0.0.1:8000 POS_API_KEY={key_show} "
        f"POS_WEBHOOK_SECRET={WEBHOOK_SECRET} .venv/Scripts/python scripts/temp_pos.py"
    )
    print("Then place a WhatsApp order on this restaurant.")
    return 0


if __name__ == "__main__":
    phone = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("POS_TEST_PHONE", "")
    if not phone:
        print("Usage: enable_partner_for_test.py +9715XXXXXXXX   (or set POS_TEST_PHONE)")
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main(phone)))
