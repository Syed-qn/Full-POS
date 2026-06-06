"""In-memory MockTemplateProvider — deterministic, no network.

Runs ``compliance.lint_template`` on create: returns ``REJECTED`` (with the
first violation as the reason) when the spec is non-compliant, otherwise
``APPROVED`` immediately. This lets the full marketing pipeline run in
tests/dev with no Meta round-trip. Selected whenever
``marketing_send_dry_run`` or ``marketing_template_provider == "mock"``.
"""
from __future__ import annotations

import uuid

from app.marketing.compliance import lint_template
from app.marketing.template_port import (
    TemplateCreateResult,
    TemplateSpec,
    TemplateStatus,
)


class MockTemplateProvider:
    def __init__(self) -> None:
        # meta_template_id -> result
        self._by_id: dict[str, TemplateCreateResult] = {}
        # name -> meta_template_id (latest create wins)
        self._id_by_name: dict[str, str] = {}

    async def create(self, spec: TemplateSpec) -> TemplateCreateResult:
        meta_template_id = uuid.uuid4().hex
        violations = lint_template(spec.to_compliance_dict())
        if violations:
            result = TemplateCreateResult(
                meta_template_id=meta_template_id,
                status=TemplateStatus.REJECTED,
                rejection_reason=violations[0],
            )
        else:
            result = TemplateCreateResult(
                meta_template_id=meta_template_id,
                status=TemplateStatus.APPROVED,
            )
        self._by_id[meta_template_id] = result
        self._id_by_name[spec.name] = meta_template_id
        return result

    async def get_status(self, meta_template_id: str) -> TemplateCreateResult:
        existing = self._by_id.get(meta_template_id)
        if existing is not None:
            return existing
        return TemplateCreateResult(
            meta_template_id=meta_template_id,
            status=TemplateStatus.DELETED,
        )

    async def delete(
        self, *, name: str, meta_template_id: str | None = None
    ) -> bool:
        template_id = meta_template_id or self._id_by_name.get(name)
        if template_id is None or template_id not in self._by_id:
            return False
        self._by_id[template_id] = TemplateCreateResult(
            meta_template_id=template_id,
            status=TemplateStatus.DELETED,
        )
        self._id_by_name.pop(name, None)
        return True
