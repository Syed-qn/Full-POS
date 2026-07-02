"""Vector knowledge base over context.txt (prompt goldmine).

Chunks context.txt, builds a TF-IDF vector index (numpy, no extra ML deps), and
retrieves the most relevant prompt-spec sections per customer turn + dialogue phase.
Injected into the conversation agent system prompt alongside OKF grounding.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.llm.prompt_goldmine import GOLDMINE_PATH, load_prompt_goldmine

_REPO_ROOT = Path(__file__).resolve().parents[3]
_INDEX_DIR = _REPO_ROOT / "var" / "prompt_kb"
_INDEX_PATH = _INDEX_DIR / "index.json"

_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_SECTION_SPLIT = re.compile(
    r"(?=^={10,}|^---\s+\d+\.|^---\s+[A-Z]|^SECTION [A-Z]|^### File:)",
    re.MULTILINE,
)
_PHASE_TAGS: dict[str, tuple[str, ...]] = {
    "ordering": ("ordering", "_ordering", "cart", "menu_show", "checkout"),
    "address_capture": ("address", "delivery", "location", "pin"),
    "awaiting_confirmation": ("confirmation", "confirm", "summary"),
    "post_order": ("post_order", "post-order", "modify", "status", "tracking"),
}

_MAX_CHUNK_CHARS = 2800
_MIN_CHUNK_CHARS = 120


@dataclass(frozen=True)
class PromptChunk:
    chunk_id: str
    title: str
    text: str
    tags: tuple[str, ...]


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def _detect_tags(title: str, text: str) -> tuple[str, ...]:
    blob = f"{title} {text}".lower()
    tags: list[str] = []
    for phase, keys in _PHASE_TAGS.items():
        if any(k in blob for k in keys):
            tags.append(phase)
    if "master prompt" in blob or "[role]" in blob:
        tags.append("framework")
    if "identity" in blob or "_identity" in blob:
        tags.append("identity")
    if "router" in blob or "completion" in blob:
        tags.append("router")
    if "complaint" in blob or "modify" in blob:
        tags.append("subagent")
    return tuple(tags)


def chunk_context_text(raw: str) -> list[PromptChunk]:
    """Split context.txt into retrieval-sized chunks with metadata tags."""
    parts = _SECTION_SPLIT.split(raw)
    chunks: list[PromptChunk] = []
    buf = ""
    buf_title = "Prompt goldmine"

    def _flush() -> None:
        nonlocal buf, buf_title
        text = buf.strip()
        if len(text) < _MIN_CHUNK_CHARS:
            return
        if len(text) > _MAX_CHUNK_CHARS:
            # Hard-split oversized sections so vectors stay focused.
            start = 0
            part_no = 0
            while start < len(text):
                piece = text[start : start + _MAX_CHUNK_CHARS].strip()
                if len(piece) >= _MIN_CHUNK_CHARS:
                    cid = hashlib.sha256(piece.encode()).hexdigest()[:16]
                    chunks.append(
                        PromptChunk(
                            chunk_id=f"{cid}-{part_no}",
                            title=f"{buf_title} (part {part_no + 1})",
                            text=piece,
                            tags=_detect_tags(buf_title, piece),
                        )
                    )
                    part_no += 1
                start += _MAX_CHUNK_CHARS
        else:
            cid = hashlib.sha256(text.encode()).hexdigest()[:16]
            chunks.append(
                PromptChunk(
                    chunk_id=cid,
                    title=buf_title,
                    text=text,
                    tags=_detect_tags(buf_title, text),
                )
            )
        buf = ""

    for part in parts:
        part = part.strip()
        if not part:
            continue
        first_line = part.split("\n", 1)[0].strip()
        if first_line.startswith("---") or first_line.startswith("SECTION") or first_line.startswith("###"):
            _flush()
            buf_title = first_line.lstrip("#- ").strip()[:120] or buf_title
            buf = part
        else:
            buf = f"{buf}\n\n{part}" if buf else part
    _flush()

    if not chunks and raw.strip():
        chunks.append(
            PromptChunk(
                chunk_id="full",
                title="Prompt goldmine",
                text=raw[:_MAX_CHUNK_CHARS],
                tags=("framework",),
            )
        )
    return chunks


def _sparse_tfidf(
    docs: list[list[str]],
) -> tuple[list[dict[str, float]], dict[str, float]]:
    """Return per-doc sparse TF-IDF vectors and the shared IDF table."""
    df: dict[str, int] = {}
    tfs: list[dict[str, float]] = []
    n = len(docs)
    for tokens in docs:
        tf: dict[str, float] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0.0) + 1.0
        for t in tf:
            df[t] = df.get(t, 0) + 1
        tfs.append(tf)

    idf = {t: math.log((1 + n) / (1 + c)) + 1.0 for t, c in df.items()}
    vectors: list[dict[str, float]] = []
    for tf in tfs:
        norm = sum(v * v for v in tf.values()) ** 0.5 or 1.0
        vec = {t: (c / norm) * idf.get(t, 1.0) for t, c in tf.items()}
        vectors.append(vec)
    return vectors, idf


def _vec_from_tokens(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    tf: dict[str, float] = {}
    for t in tokens:
        tf[t] = tf.get(t, 0.0) + 1.0
    norm = sum(v * v for v in tf.values()) ** 0.5 or 1.0
    return {t: (c / norm) * idf.get(t, 1.0) for t, c in tf.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a.get(k, 0.0) * v for k, v in b.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _source_sha256() -> str:
    return hashlib.sha256(GOLDMINE_PATH.read_bytes()).hexdigest()


def build_index() -> dict:
    """Build serializable TF-IDF index from context.txt."""
    raw = load_prompt_goldmine()
    chunks = chunk_context_text(raw)
    tokenized = [_tokenize(c.title + " " + c.text) for c in chunks]
    vectors, idf = _sparse_tfidf(tokenized)
    return {
        "source_sha256": _source_sha256(),
        "chunk_count": len(chunks),
        "chunks": [
            {
                "chunk_id": c.chunk_id,
                "title": c.title,
                "text": c.text,
                "tags": list(c.tags),
                "vector": vectors[i],
            }
            for i, c in enumerate(chunks)
        ],
        "idf": idf,
    }


def save_index(index: dict | None = None) -> Path:
    index = index or build_index()
    _INDEX_DIR.mkdir(parents=True, exist_ok=True)
    _INDEX_PATH.write_text(json.dumps(index), encoding="utf-8")
    return _INDEX_PATH


@lru_cache(maxsize=1)
def _load_index_cached() -> dict:
    if not GOLDMINE_PATH.is_file():
        raise FileNotFoundError(f"Missing prompt goldmine: {GOLDMINE_PATH}")
    current_sha = _source_sha256()
    if _INDEX_PATH.is_file():
        try:
            data = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
            if data.get("source_sha256") == current_sha and data.get("chunks"):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return build_index()


def sync_prompt_kb_index() -> dict:
    """Rebuild index when context.txt changes; persist to var/prompt_kb/."""
    _load_index_cached.cache_clear()
    index = build_index()
    save_index(index)
    _load_index_cached.cache_clear()
    return index


def retrieve_prompt_kb(
    query: str,
    *,
    phase: str | None = None,
    top_k: int = 3,
    max_chars: int = 2400,
) -> list[dict]:
    """Vector-retrieve top prompt-spec chunks for this turn."""
    index = _load_index_cached()
    if index.get("source_sha256") != _source_sha256():
        index = sync_prompt_kb_index()

    idf: dict[str, float] = index.get("idf") or {}
    chunks: list[dict] = index.get("chunks") or []
    if not chunks:
        return []

    q_tokens = _tokenize(query)
    if phase:
        q_tokens.extend(_tokenize(phase))
        for tag in _PHASE_TAGS.get(phase, ()):
            q_tokens.append(tag)
    # Always bias toward master framework + identity.
    q_tokens.extend(["role", "constraints", "task", "prompt", "ordering"])

    q_vec = _vec_from_tokens(q_tokens, idf)
    scored: list[tuple[float, dict]] = []
    for ch in chunks:
        vec = ch.get("vector") or {}
        score = _cosine(q_vec, vec)
        tags = ch.get("tags") or []
        if phase and phase in tags:
            score += 0.15
        if "framework" in tags or "identity" in tags:
            score += 0.05
        scored.append((score, ch))

    scored.sort(key=lambda x: x[0], reverse=True)
    picked: list[dict] = []
    used = 0
    seen: set[str] = set()
    for _score, ch in scored:
        cid = ch.get("chunk_id") or ""
        if cid in seen:
            continue
        text = (ch.get("text") or "").strip()
        if not text:
            continue
        title = (ch.get("title") or "Prompt spec").strip()
        block = f"### {title}\n{text}"
        if used + len(block) > max_chars and picked:
            break
        picked.append({"chunk_id": cid, "title": title, "text": text, "score": _score})
        seen.add(cid)
        used += len(block)
        if len(picked) >= top_k:
            break
    return picked


def format_prompt_kb_block(
    chunks: list[dict],
    *,
    max_chars: int = 2400,
) -> str:
    """Render retrieved chunks for system-prompt injection."""
    if not chunks:
        return ""
    lines = [
        "[PROMPT_KB]",
        "Authoritative prompt specifications retrieved from context.txt (vector KB).",
        "Follow these rules when they clarify phase behaviour; they override vague chat history.",
        "Cite as [prompt_kb:<chunk_id>] when applying a rule.",
        "",
    ]
    used = len("\n".join(lines))
    for ch in chunks:
        title = ch.get("title") or "Prompt spec"
        cid = ch.get("chunk_id") or "?"
        body = (ch.get("text") or "").strip()
        if len(body) > 900:
            body = body[:897].rstrip() + "…"
        block = f"### [{cid}] {title}\n{body}\n"
        if used + len(block) > max_chars:
            break
        lines.append(block)
        used += len(block)
    return "\n".join(lines).strip()


def prompt_kb_grounding(
    query: str,
    *,
    phase: str | None = None,
    top_k: int = 3,
    max_chars: int = 2400,
) -> str:
    """One-shot retrieve + format for engine injection."""
    hits = retrieve_prompt_kb(query, phase=phase, top_k=top_k, max_chars=max_chars)
    return format_prompt_kb_block(hits, max_chars=max_chars)