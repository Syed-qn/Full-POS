"""MetaTemplateProvider — real WhatsApp Business message-template management.

Talks to the Graph API (``httpx.AsyncClient``) under the WABA id:

- ``create``     → POST   /{waba_id}/message_templates
- ``get_status`` → GET    /{waba_id}/message_templates?name=
- ``delete``     → DELETE /{waba_id}/message_templates?name=

Follows ``whatsapp/cloud_provider.py`` conventions (Graph base version,
bearer token via ``SecretStr.get_secret_value()``, 10s timeout).

Guard: the constructor raises if ``marketing_send_dry_run`` is True — this
provider must never be instantiated in tests; tests always use the mock.

Image header support: real resumable upload (per research whatsapp-cloud-api-notes.md §5.1):
- If header IMAGE and no pre 'header_handle' but has 'image_url'/'url', _upload_image_header
  does the 2-step (init session on /{app_id}/uploads?access_token= , then file post with
  OAuth + file_offset=0) to obtain 'h:...' handle, injects into components.example.header_handle.
- Bytes from http ref (fetch) or fs path (relative resolved via settings.upload_dir).
- All values (version, app_id, token) from settings only. No hardcodes.
See docs/research/... + spec §4.7 + GAP_LIST #3 + phase-6 plan.
Auto-delete EOD and poll are in worker/service (not here).
"""
from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.marketing.template_port import (
    TemplateCreateResult,
    TemplateSpec,
    TemplateStatus,
)

_BODY_VAR_RE = re.compile(r"\{\{\s*(\d+)\s*\}\}")


def _body_example_values(body: str) -> list[str] | None:
    """One sample value per ``{{n}}`` placeholder in the body, in order.

    Meta REQUIRES an example for every BODY variable: without it an IMAGE-header
    template is rejected with a hard 400 (subcode 2388043 "component of type BODY
    is missing expected field(s) (example)") and a text-only template is
    auto-rejected. ``{{1}}`` is the customer's name by this app's convention
    (copywriter greets with it); generic sample for any further variables.
    """
    nums = sorted({int(n) for n in _BODY_VAR_RE.findall(body or "")})
    if not nums:
        return None
    return ["Ahmed" if i == 1 else "Sample" for i in nums]


def _get_graph_base() -> str:
    """Dynamic from settings (no module hardcode)."""
    v = get_settings().graph_api_version
    return f"https://graph.facebook.com/{v}"


def _build_components(spec: TemplateSpec, *, header_handle: str | None = None) -> list[dict[str, Any]]:
    """Build components; optional override handle for IMAGE after upload."""
    components: list[dict[str, Any]] = []

    if spec.header:
        header_type = spec.header.get("type", "text").upper()
        comp: dict[str, Any] = {"type": "HEADER", "format": header_type}
        if header_type == "TEXT":
            comp["text"] = spec.header.get("text", "")
        elif header_type == "IMAGE":
            h = header_handle or spec.header.get("header_handle")
            comp["example"] = {"header_handle": [h] if h else []}
        components.append(comp)

    body_comp: dict[str, Any] = {"type": "BODY", "text": spec.body}
    body_examples = _body_example_values(spec.body)
    if body_examples:
        body_comp["example"] = {"body_text": [body_examples]}
    components.append(body_comp)

    if spec.footer:
        components.append({"type": "FOOTER", "text": spec.footer})

    if spec.buttons:
        buttons: list[dict[str, Any]] = []
        for b in spec.buttons:
            btn_type = b.get("type", "QUICK_REPLY")
            btn: dict[str, Any] = {"type": btn_type, "text": b.get("label", "")}
            if btn_type == "URL":
                btn["url"] = b.get("url", "")
            elif btn_type == "PHONE_NUMBER":
                btn["phone_number"] = b.get("phone_number", "")
            buttons.append(btn)
        components.append({"type": "BUTTONS", "buttons": buttons})

    return components


async def _fetch_bytes(ref: str, upload_dir: str) -> tuple[bytes, str]:
    """Return (bytes, filename) for ref (http or fs path). Minimal, no extra deps."""
    if ref.startswith("http://") or ref.startswith("https://"):
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.get(ref)
            r.raise_for_status()
            fname = ref.split("/")[-1].split("?")[0] or "header.jpg"
            return r.content, fname
    # fs path: relative -> under upload_dir
    path = ref if os.path.isabs(ref) else os.path.join(upload_dir, ref)
    with open(path, "rb") as f:
        data = f.read()
    fname = os.path.basename(path) or "header.jpg"
    return data, fname


def _status_from_meta(raw: str) -> TemplateStatus:
    try:
        return TemplateStatus(raw.lower())
    except ValueError:
        return TemplateStatus.PENDING


class MetaTemplateProvider:
    def __init__(self) -> None:
        settings = get_settings()
        if settings.marketing_send_dry_run:
            raise RuntimeError(
                "MetaTemplateProvider must not be instantiated under "
                "marketing_send_dry_run — use MockTemplateProvider."
            )
        self._token = settings.wa_access_token.get_secret_value()
        self._waba_id = settings.wa_business_account_id
        self._app_id = settings.wa_app_id
        self._upload_dir = settings.upload_dir
        self._graph_base = _get_graph_base()

    @property
    def _base_url(self) -> str:
        return f"{self._graph_base}/{self._waba_id}/message_templates"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def _upload_image_header(self, image_ref: str) -> str:
        """Real resumable upload for IMAGE header example.
        Returns the 'h:...' handle for use in template create.
        2 steps per whatsapp-cloud-api-notes §5.1 (app_id not waba).
        Uses settings for app_id/token/dir/version (no hardcodes).
        """
        if not self._app_id:
            raise RuntimeError("wa_app_id required in settings for resumable image header upload")
        data, fname = await _fetch_bytes(image_ref, self._upload_dir)
        file_len = len(data)
        file_type = "image/jpeg" if fname.lower().endswith((".jpg", ".jpeg")) else "image/png"

        # Step 1: init upload session (access_token in QUERY)
        init_url = f"{self._graph_base}/{self._app_id}/uploads"
        q = urlencode({
            "file_name": fname,
            "file_length": str(file_len),
            "file_type": file_type,
            "access_token": self._token,
        })
        async with httpx.AsyncClient(timeout=30.0) as client:
            r1 = await client.post(f"{init_url}?{q}")
            r1.raise_for_status()
            session_id = r1.json()["id"]

            # Step 2: upload bytes (OAuth header + offset 0)
            up_headers = {
                "Authorization": f"OAuth {self._token}",
                "file_offset": "0",
            }
            r2 = await client.post(
                f"{self._graph_base}/{session_id}",
                content=data,
                headers=up_headers,
            )
            r2.raise_for_status()
            h = r2.json()["h"]
            return h

    async def create(self, spec: TemplateSpec) -> TemplateCreateResult:
        header_handle: str | None = None
        if spec.header and spec.header.get("type", "").upper() == "IMAGE":
            h = spec.header.get("header_handle")
            if not h:
                ref = spec.header.get("image_url") or spec.header.get("url") or spec.header.get("file")
                if ref:
                    header_handle = await self._upload_image_header(ref)

        payload = {
            "name": spec.name,
            "language": spec.language,
            "category": spec.category.upper(),
            "components": _build_components(spec, header_handle=header_handle),
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self._base_url, json=payload, headers=self._headers
            )
        resp.raise_for_status()
        data = resp.json()
        return TemplateCreateResult(
            meta_template_id=str(data["id"]),
            status=_status_from_meta(data.get("status", "PENDING")),
        )

    async def get_status(self, meta_template_id: str) -> TemplateCreateResult:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                self._base_url,
                params={"fields": "id,name,status", "limit": 100},
                headers=self._headers,
            )
        resp.raise_for_status()
        for tpl in resp.json().get("data", []):
            if str(tpl.get("id")) == meta_template_id:
                return TemplateCreateResult(
                    meta_template_id=meta_template_id,
                    status=_status_from_meta(tpl.get("status", "PENDING")),
                )
        return TemplateCreateResult(
            meta_template_id=meta_template_id,
            status=TemplateStatus.DELETED,
        )

    async def delete(
        self, *, name: str, meta_template_id: str | None = None
    ) -> bool:
        params: dict[str, str] = {"name": name}
        if meta_template_id is not None:
            params["hsm_id"] = meta_template_id
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(
                self._base_url, params=params, headers=self._headers
            )
        resp.raise_for_status()
        return bool(resp.json().get("success", False))
