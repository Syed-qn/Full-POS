from pydantic import BaseModel, ConfigDict


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
