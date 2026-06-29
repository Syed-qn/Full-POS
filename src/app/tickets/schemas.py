from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    customer_phone: str | None = None
    customer_name: str | None = None
    order_id: int | None
    source_message: str | None
    evidence: list
    category: str | None
    status: str
    assigned_to: str | None
    resolution_action: str
    resolution_amount_aed: Decimal | None
    replacement_order_id: int | None
    resolution_note: str | None
    resolved_at: datetime | None
    created_at: datetime


class TicketResolveIn(BaseModel):
    action: str = Field(
        pattern="^(wallet_refund|replacement|create_replacement|resolved_no_action)$"
    )
    note: str = Field(min_length=1)
    amount: Decimal | None = None
    replacement_order_id: int | None = None
