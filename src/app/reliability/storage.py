"""Where a backup snapshot actually lives.

Backups used to be written to ``os.getcwd()/var/backups`` with no configuration
hook that anyone had set. On a container platform that is the container's own
disk: the file survives exactly until the next deploy or restart, while the
``backup_jobs`` row survives forever. The dashboard therefore showed a list of
"completed" backups whose files had already been deleted — the worst possible
failure, because it reads as safety.

This module makes the destination explicit and gives the UI something honest to
display:

* ``local``  — a directory on disk. Durable ONLY if that path is a mounted
  volume; ``APP_BACKUP_DIR`` must point at one in production.
* ``s3``     — any S3-compatible bucket (AWS S3, Cloudflare R2, MinIO, Backblaze
  B2). Off-box, so it survives the machine itself.

Paths are stored as URIs (``file:///...`` or ``s3://bucket/key``) so a row
records which backend wrote it. Bare filesystem paths written by the previous
implementation still resolve — see ``_parse``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from anyio import to_thread

from app.config import get_settings


class BackupStorageError(RuntimeError):
    """Raised when the configured destination cannot be used."""


@dataclass(frozen=True)
class _Ref:
    """A parsed storage location: either a local file or a bucket key."""

    backend: str  # local | s3
    path: Path | None = None
    bucket: str | None = None
    key: str | None = None


def _parse(uri: str) -> _Ref:
    if uri.startswith("s3://"):
        parsed = urlparse(uri)
        return _Ref(backend="s3", bucket=parsed.netloc, key=parsed.path.lstrip("/"))
    if uri.startswith("file://"):
        # Path.as_uri() percent-encodes, so "Full POS" comes back as "Full%20POS"
        # and the un-decoded path does not exist. Decode before touching disk.
        rest = unquote(uri[7:])
        # Windows: "/C:/x" must lose its leading slash. POSIX: "/var/x" must keep
        # it, or an absolute path silently becomes a relative one.
        if re.match(r"^/[A-Za-z]:[\\/]", rest):
            rest = rest[1:]
        return _Ref(backend="local", path=Path(rest))
    # Legacy rows: a bare filesystem path, written before URIs existed.
    return _Ref(backend="local", path=Path(uri))


def _local_dir() -> Path:
    settings = get_settings()
    root = settings.backup_dir or os.path.join(os.getcwd(), "var", "backups")
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _s3_configured() -> bool:
    return bool(get_settings().backup_s3_bucket)


def _s3_client():
    """Build a boto3 client. Imported lazily — boto3 is an optional extra."""
    try:
        import boto3  # noqa: PLC0415
    except ModuleNotFoundError as exc:  # pragma: no cover - env dependent
        raise BackupStorageError(
            "APP_BACKUP_S3_BUCKET is set but boto3 is not installed. "
            "Install it with: pip install -e '.[s3]'"
        ) from exc
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.backup_s3_endpoint_url or None,
        region_name=s.backup_s3_region or None,
        aws_access_key_id=s.backup_s3_access_key_id.get_secret_value() or None,
        aws_secret_access_key=s.backup_s3_secret_access_key.get_secret_value() or None,
    )


def active_backend() -> str:
    return "s3" if _s3_configured() else "local"


def _is_separate_mount(path: Path) -> bool | None:
    """Is `path` on a different filesystem from the container's root?

    A mounted volume is a different device from ``/``; a plain directory inside
    the image is the same device. Comparing st_dev is a real check, which matters
    because the alternative — trusting APP_BACKUP_DIR_IS_VOLUME — turns the
    dashboard's durability badge green whenever the operator *says* a volume is
    mounted, including when the mount silently failed and the files are still
    being written to disposable disk.

    Returns None when the question cannot be answered (Windows, or an unreadable
    root), so the caller falls back to the operator's assertion instead of
    reporting a confident wrong answer.
    """
    if os.name != "posix":
        return None
    try:
        return path.stat().st_dev != Path("/").stat().st_dev
    except OSError:
        return None


def describe_target() -> dict:
    """What the dashboard shows in place of the old literal 'APP_BACKUP_DIR'.

    ``durable`` is the only field that matters operationally: it answers "will
    this still be here after a redeploy?". For local storage we cannot know
    whether the directory is a mounted volume, so it is reported as unknown
    unless the operator has confirmed it via APP_BACKUP_DIR_IS_VOLUME.
    """
    s = get_settings()
    if _s3_configured():
        return {
            "backend": "s3",
            "location": f"s3://{s.backup_s3_bucket}/{s.backup_s3_prefix}".rstrip("/"),
            "endpoint": s.backup_s3_endpoint_url or "aws",
            "durable": True,
            "note": "Off-box object storage. Survives redeploys and host loss.",
        }
    path = _local_dir()
    mounted = _is_separate_mount(path)

    if mounted is True:
        durable, note = True, f"Mounted volume ({path}) — survives redeploys."
    elif mounted is False:
        # The decisive case: the operator may have set the flag, but the
        # directory demonstrably lives inside the image.
        durable = False
        note = (
            f"{path} is NOT a mounted volume — it is inside the container image, "
            "so files are LOST on redeploy or restart."
            + (
                " APP_BACKUP_DIR_IS_VOLUME is set to true, but the filesystem says "
                "otherwise: check the volume is attached and its mount path matches."
                if s.backup_dir_is_volume
                else " Attach a volume and point APP_BACKUP_DIR at its mount path, "
                "or set APP_BACKUP_S3_BUCKET for off-box storage."
            )
        )
    else:  # cannot tell (e.g. local Windows dev)
        durable = bool(s.backup_dir_is_volume)
        note = (
            "Declared durable by APP_BACKUP_DIR_IS_VOLUME — this platform cannot "
            "verify whether it is really a mounted volume."
            if durable
            else "Local directory, not confirmed as a mounted volume. Point "
            "APP_BACKUP_DIR at a volume, or set APP_BACKUP_S3_BUCKET for off-box storage."
        )

    return {
        "backend": "local",
        "location": str(path),
        "endpoint": None,
        "durable": durable,
        "mount_verified": mounted,
        "note": note,
    }


async def put_backup(filename: str, raw: bytes) -> str:
    """Write a snapshot and return the URI that locates it."""
    if _s3_configured():
        s = get_settings()
        key = f"{s.backup_s3_prefix.strip('/')}/{filename}".lstrip("/")
        client = _s3_client()
        await to_thread.run_sync(
            lambda: client.put_object(
                Bucket=s.backup_s3_bucket,
                Key=key,
                Body=raw,
                ContentType="application/json",
            )
        )
        return f"s3://{s.backup_s3_bucket}/{key}"
    path = _local_dir() / filename
    await to_thread.run_sync(path.write_bytes, raw)
    return path.as_uri()


async def get_backup(uri: str) -> bytes:
    ref = _parse(uri)
    if ref.backend == "s3":
        client = _s3_client()
        obj = await to_thread.run_sync(
            lambda: client.get_object(Bucket=ref.bucket, Key=ref.key)
        )
        return await to_thread.run_sync(obj["Body"].read)
    assert ref.path is not None
    return await to_thread.run_sync(ref.path.read_bytes)


async def backup_exists(uri: str | None) -> bool:
    if not uri:
        return False
    ref = _parse(uri)
    if ref.backend == "s3":
        client = _s3_client()

        def _head() -> bool:
            try:
                client.head_object(Bucket=ref.bucket, Key=ref.key)
                return True
            except Exception:  # noqa: BLE001 - any miss means "not retrievable"
                return False

        return await to_thread.run_sync(_head)
    assert ref.path is not None
    return await to_thread.run_sync(ref.path.exists)
