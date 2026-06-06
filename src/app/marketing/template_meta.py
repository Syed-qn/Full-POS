"""MetaTemplateProvider — real WhatsApp Business message-template management.

Talks to the Graph API (``httpx.AsyncClient``) under the WABA id:

- ``create``     → POST   /{waba_id}/message_templates
- ``get_status`` → GET    /{waba_id}/message_templates?name=
- ``delete``     → DELETE /{waba_id}/message_templates?name=

Follows ``whatsapp/cloud_provider.py`` conventions (Graph base version,
bearer token via ``SecretStr.get_secret_value()``, 10s timeout).

Guard: the constructor raises if ``marketing_send_dry_run`` is True — this
provider must never be instantiated in tests; tests always use the mock.

NOTE: image headers require Meta's resumable-upload handle. For now this
adapter accepts a pre-uploaded ``header_handle`` on an image header dict and
forwards it; TODO: implement the resumable upload flow.
See docs/research/whatsapp-cloud-api-notes.md §5.1.
"""
from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings
from app.marketing.template_port import (
    TemplateCreateResult,
    TemplateSpec,
    TemplateStatus,
)

_GRAPH_BASE = "https://graph.facebook.com/v21.0"


def _build_components(spec: TemplateSpec) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []

    if spec.header:
        header_type = spec.header.get("type", "text").upper()
        comp: dict[str, Any] = {"type": "HEADER", "format": header_type}
        if header_type == "TEXT":
            comp["text"] = spec.header.get("text", "")
        elif header_type == "IMAGE":
            # Resumable-upload handle (pre-uploaded) — TODO: real upload flow.
            handle = spec.header.get("header_handle")
            comp["example"] = {"header_handle": [handle] if handle else []}
        components.append(comp)

    components.append({"type": "BODY", "text": spec.body})

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

    @property
    def _base_url(self) -> str:
        return f"{_GRAPH_BASE}/{self._waba_id}/message_templates"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def create(self, spec: TemplateSpec) -> TemplateCreateResult:
        payload = {
            "name": spec.name,
            "language": spec.language,
            "category": spec.category.upper(),
            "components": _build_components(spec),
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
