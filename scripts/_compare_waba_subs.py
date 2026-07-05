"""Compare WABA webhook subscription between restaurants."""
from __future__ import annotations

import asyncio
import json
import os

import asyncpg
import httpx


async def main() -> None:
    db = os.environ.get("APP_EXTERNAL_DB") or open(".env").read().split("APP_EXTERNAL_DB=")[1].split("\n")[0].strip()
    conn = await asyncpg.connect(db, ssl="require")
    for rid in (1, 2):
        r = await conn.fetchrow("SELECT id, name, settings FROM restaurants WHERE id=$1", rid)
        s = r["settings"]
        if isinstance(s, str):
            s = json.loads(s)
        token = s["wa_access_token"]
        waba = s["wa_business_account_id"]
        pid = s["wa_phone_number_id"]
        headers = {"Authorization": f"Bearer {token}"}
        base = "https://graph.facebook.com/v21.0"
        async with httpx.AsyncClient(timeout=30) as cl:
            print(f"\n=== {r['name']} (id={rid}) ===")
            r1 = await cl.get(f"{base}/{waba}/subscribed_apps", headers=headers)
            print("subscribed_apps:", r1.status_code, r1.text[:600])
            r2 = await cl.get(
                f"{base}/{pid}",
                params={
                    "fields": (
                        "display_phone_number,status,verified_name,platform_type,"
                        "code_verification_status,quality_rating,messaging_limit_tier"
                    )
                },
                headers=headers,
            )
            print("phone:", r2.status_code, r2.text)
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())