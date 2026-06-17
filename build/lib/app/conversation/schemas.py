from pydantic import BaseModel, ConfigDict, Field


class TakeoverIn(BaseModel):
    """Toggle manager manual-takeover for a conversation."""

    active: bool = True


class SendMessageIn(BaseModel):
    """A free-text message the manager sends to the customer from the dashboard."""

    text: str = Field(min_length=1, max_length=4096)


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    restaurant_id: int
    phone: str
    counterpart: str
    state: dict
    manual_takeover: bool
    taken_over_by: int | None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    direction: str
    wa_message_id: str | None
    type: str
    payload: dict
    ts: int


# ── Manager-dashboard (React Conversations screen) read models ───────────────
# Shapes match frontend/src/lib/types.ts ConversationOut / MessageOut exactly.
class DashboardConversationOut(BaseModel):
    id: int
    phone: str
    counterpart: str
    manual_takeover: bool
    last_message_preview: str | None
    unread: bool
    updated_at: str


class DashboardMessageOut(BaseModel):
    id: int
    direction: str
    type: str
    payload: dict
    ts: int
