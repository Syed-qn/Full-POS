"""Re-compress Lims dish images + Publish so WhatsApp catalog cards all render."""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main() -> None:
    import asyncpg

    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from app.catalog.sync_service import push_dishes_to_meta
    from app.menu.image_catalog import (
        CATALOG_IMAGE_MAX_BYTES,
        compress_for_catalog_image,
        media_path_from_url,
    )

    db = None
    for line in open(".env"):
        if line.startswith("APP_EXTERNAL_DB="):
            db = line.split("=", 1)[1].strip().strip('"')
    conn = await asyncpg.connect(db, ssl="require")

    rows = await conn.fetch(
        """
        SELECT d.id, d.name, d.image_url
        FROM dishes d JOIN menus m ON d.menu_id = m.id
        WHERE d.restaurant_id = 2 AND m.status = 'active' AND d.image_url IS NOT NULL
        """
    )
    for r in rows:
        path = media_path_from_url(r["image_url"])
        if not path:
            continue
        media = await conn.fetchrow(
            "SELECT path, length(data) AS sz FROM marketing_media WHERE path=$1", path
        )
        if not media:
            print(f"SKIP {r['name']}: no media row for {path}")
            continue
        print(f"{r['name']}: {media['sz']} bytes before")
        if media["sz"] <= CATALOG_IMAGE_MAX_BYTES:
            print("  already small enough")
            continue
        blob = await conn.fetchval("SELECT data FROM marketing_media WHERE path=$1", path)
        new_data, _ = compress_for_catalog_image(bytes(blob))
        await conn.execute(
            "UPDATE marketing_media SET data=$1, content_type='image/jpeg' WHERE path=$2",
            new_data,
            path,
        )
        print(f"  -> {len(new_data)} bytes JPEG")

    await conn.close()

    prod_url = db.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(prod_url)
    Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        result = await push_dishes_to_meta(
            session, restaurant_id=2, wait_for_ingest=True
        )
        await session.commit()
        print(f"PUBLISH: pushed={result.pushed} updated={result.push_updated}")
    print("DONE — wait 2-5 min for Meta image fetch, then test menu on Lims.")


if __name__ == "__main__":
    asyncio.run(main())