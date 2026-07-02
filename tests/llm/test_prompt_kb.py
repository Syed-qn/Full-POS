"""Vector knowledge base over context.txt."""

from app.llm.prompt_kb import (
    chunk_context_text,
    format_prompt_kb_block,
    prompt_kb_grounding,
    retrieve_prompt_kb,
    sync_prompt_kb_index,
)


def test_chunk_context_text_splits_sections():
    raw = (
        "=== SECTION A ===\n"
        + ("ordering rule alpha " * 40)
        + "\n--- 2. ADDRESS PHASE ---\n"
        + ("address capture beta " * 40)
    )
    chunks = chunk_context_text(raw)
    assert len(chunks) >= 2
    assert any("ordering" in c.tags or "ORDERING" in c.title.upper() for c in chunks)


def test_sync_and_retrieve_ordering_phase():
    index = sync_prompt_kb_index()
    assert index["chunk_count"] >= 10
    hits = retrieve_prompt_kb(
        "add chicken biryani to cart",
        phase="ordering",
        top_k=3,
        max_chars=3000,
    )
    assert hits
    assert all(h.get("text") for h in hits)


def test_retrieve_boosts_phase_relevant_chunks():
    hits = retrieve_prompt_kb(
        "share your delivery address pin",
        phase="address_capture",
        top_k=5,
        max_chars=4000,
    )
    blob = " ".join(h["title"] + " " + h["text"] for h in hits).lower()
    assert "address" in blob or "location" in blob or "delivery" in blob


def test_format_prompt_kb_block_has_header_and_cites():
    hits = retrieve_prompt_kb("menu show full menu", phase="ordering", top_k=2)
    block = format_prompt_kb_block(hits)
    assert "[PROMPT_KB]" in block
    assert "[prompt_kb:" in block
    assert "###" in block


def test_prompt_kb_grounding_end_to_end():
    block = prompt_kb_grounding("done checkout proceed", phase="ordering", top_k=2)
    assert block.startswith("[PROMPT_KB]")
    assert len(block) > 200