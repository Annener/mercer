from __future__ import annotations

from pydantic import BaseModel


class ChatCreate(BaseModel):
    title: str | None = None
    domain_id: str
    vault_id: str | None = None
    campaign_id: str | None = None


class ChatResponse(BaseModel):
    chat_id: str
    title: str
    domain_id: str | None = None
    vault_id: str | None = None
    campaign_id: str | None = None


class ChatListResponse(BaseModel):
    chats: list[ChatResponse]


class MessageResponse(BaseModel):
    message_id: str
    content: str


class SendMessageRequest(BaseModel):
    content: str
