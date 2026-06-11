"""Manager-dashboard read API for WhatsApp conversations.

Backs the React Conversations screen (frontend/src/screens/ConversationsScreen).
Read-only for now: list conversations + fetch one conversation's messages,
tenant-scoped to the logged-in restaurant.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.conversation import service
from app.conversation.schemas import DashboardConversationOut, DashboardMessageOut
from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


@router.get("", response_model=list[DashboardConversationOut])
async def list_conversations(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> list[DashboardConversationOut]:
    rows = await service.list_dashboard_conversations(session, restaurant_id=restaurant.id)
    return [DashboardConversationOut(**row) for row in rows]


@router.get("/{conversation_id}/messages", response_model=list[DashboardMessageOut])
async def list_messages(
    conversation_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> list[DashboardMessageOut]:
    messages = await service.get_dashboard_messages(
        session, restaurant_id=restaurant.id, conversation_id=conversation_id
    )
    if messages is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return [
        DashboardMessageOut(
            id=m.id,
            direction=m.direction,
            type=m.type,
            payload=service.message_view_payload(m),
            ts=m.ts,
        )
        for m in messages
    ]
