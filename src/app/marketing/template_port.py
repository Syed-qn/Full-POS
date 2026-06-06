"""TemplatePort — provider-agnostic port for WhatsApp message templates.

Defines the data contracts (``TemplateSpec``, ``TemplateCreateResult``,
``TemplateStatus``) and the ``TemplatePort`` Protocol implemented by
``MockTemplateProvider`` (tests/dev) and ``MetaTemplateProvider`` (prod).
See plan Task 14.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class TemplateStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAUSED = "paused"
    DISABLED = "disabled"
    DELETED = "deleted"


@dataclass
class TemplateSpec:
    name: str
    language: str
    category: str  # "marketing"
    body: str
    header: dict | None = None
    footer: str | None = None
    buttons: list = field(default_factory=list)

    def to_compliance_dict(self) -> dict:
        """Shape expected by ``compliance.lint_template`` (dict-based linter)."""
        return {
            "name": self.name,
            "body": self.body,
            "header": self.header,
            "footer": self.footer,
            "buttons": self.buttons,
        }


@dataclass
class TemplateCreateResult:
    meta_template_id: str
    status: TemplateStatus
    rejection_reason: str | None = None


class TemplatePort(Protocol):
    async def create(self, spec: TemplateSpec) -> TemplateCreateResult: ...

    async def get_status(self, meta_template_id: str) -> TemplateCreateResult: ...

    async def delete(
        self, *, name: str, meta_template_id: str | None = None
    ) -> bool: ...
