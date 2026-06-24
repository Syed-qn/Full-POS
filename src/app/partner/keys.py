"""Partner API-key generation + hashing.

Keys are high-entropy random tokens, so a single fast SHA-256 is sufficient and
appropriate (unlike passwords, there is no low-entropy input to slow-hash). The
plaintext key is returned to the caller once and never stored — only its hash.
"""
import hashlib
import secrets

# Visible product prefix so a leaked key is recognisable and greppable.
KEY_PREFIX = "rk_live_"
# Length of the leading fragment kept (non-secret) for dashboard display.
_DISPLAY_PREFIX_LEN = len(KEY_PREFIX) + 6


def hash_api_key(full_key: str) -> str:
    """SHA-256 hex digest of a full API key (what we store and look up by)."""
    return hashlib.sha256(full_key.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Mint a new key. Returns ``(full_key, key_prefix, key_hash)``.

    ``full_key`` is shown to the manager once; only ``key_prefix`` (display) and
    ``key_hash`` (lookup) are persisted.
    """
    full_key = f"{KEY_PREFIX}{secrets.token_hex(16)}"  # 32 hex chars of entropy
    return full_key, full_key[:_DISPLAY_PREFIX_LEN], hash_api_key(full_key)
