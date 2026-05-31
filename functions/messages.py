from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..httpreq import Requester


def user_ref(user_id: int) -> dict[str, Any]:
    return {"user": {"userId": user_id}}


def channel_ref(community_id: int, channel_id: int) -> dict[str, Any]:
    return {"channel": {"communityId": community_id, "channelId": channel_id}}


def group_ref(group_id: int) -> dict[str, Any]:
    return {"group": {"groupId": group_id}}


def self_ref() -> dict[str, Any]:
    return {"self": {}}


@dataclass(slots=True)
class Message:
    chat_ref: dict[str, Any]
    id: int
    author_id: int
    content: str
    reply_to: int | None = None
    media: list[dict[str, Any]] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    edited_at: int | None = None
    type: int | None = None
    forward: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        return cls(
            chat_ref=data["chatRef"],
            id=data["messageId"],
            author_id=data["authorId"],
            content=data.get("message", ""),
            reply_to=data.get("replyTo"),
            media=data.get("media", []),
            entities=data.get("entities", []),
            edited_at=data.get("editedAt"),
            type=data.get("type"),
            forward=data.get("forward"),
            raw=data,
        )


class MessagesAPI:
    def __init__(self, requester: Requester):
        self.requester = requester

    async def send(
        self,
        chat_ref: dict[str, Any],
        content: str,
        *,
        reply_to: int | None = None,
        media: list[dict[str, Any]] | None = None,
        entities: list[dict[str, Any]] | None = None,
    ) -> int:
        payload: dict[str, Any] = {
            "chatRef": chat_ref,
            "message": content,
        }
        if reply_to is not None:
            payload["replyTo"] = reply_to
        if media is not None:
            payload["media"] = media
        if entities is not None:
            payload["entities"] = entities

        result = await self.requester.request("messagesSendMessage", payload)
        return result["sentMessage"]["messageId"]

    async def get_history(
        self,
        chat_ref: dict[str, Any],
        *,
        limit: int = 50,
        since: int | None = None,
        before: int | None = None,
        around: int | None = None,
    ) -> list[Message]:
        payload: dict[str, Any] = {
            "chatRef": chat_ref,
            "limit": limit,
        }
        if since is not None:
            payload["since"] = since
        if before is not None:
            payload["before"] = before
        if around is not None:
            payload["around"] = around

        result = await self.requester.request("messagesGetHistory", payload)
        return [Message.from_dict(message) for message in result["messages"].get("messages", [])]

    async def delete(self, chat_ref: dict[str, Any], message_ids: list[int]) -> None:
        await self.requester.request("messagesDeleteMessage", {
            "chatRef": chat_ref,
            "messageIds": message_ids,
        })

    async def edit(
        self,
        chat_ref: dict[str, Any],
        message_id: int,
        *,
        content: str | None = None,
        remove_media: bool = False,
        media: list[dict[str, Any]] | None = None,
        entities: list[dict[str, Any]] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chatRef": chat_ref,
            "messageId": message_id,
            "removeMedia": remove_media,
        }
        if content is not None:
            payload["message"] = content
        if media is not None:
            payload["media"] = media
        if entities is not None:
            payload["entities"] = entities
        await self.requester.request("messagesEditMessage", payload)

    async def forward(self, chat_ref: dict[str, Any], from_ref: dict[str, Any], message_ids: list[int]) -> None:
        await self.requester.request("messagesForwardMessage", {
            "chatRef": chat_ref,
            "from": from_ref,
            "messageIds": message_ids,
        })

    async def search(
        self,
        chat_ref: dict[str, Any],
        query: str,
        *,
        scoped: bool = True,
        since: int | None = None,
        before: int | None = None,
    ) -> list[Message]:
        payload: dict[str, Any] = {
            "chatRef": chat_ref,
            "query": query,
            "scoped": scoped,
        }
        if since is not None:
            payload["since"] = since
        if before is not None:
            payload["before"] = before
        result = await self.requester.request("messagesSearch", payload)
        return [Message.from_dict(message) for message in result["messages"].get("messages", [])]

    async def get_embed_preview(
        self,
        content: str,
        *,
        entities: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"message": content}
        if entities is not None:
            payload["entities"] = entities
        result = await self.requester.request("messagesGetEmbedPreview", payload)
        return result["mediaEmbed"]

    async def report(self, chat_ref: dict[str, Any], message_id: int, reason: str) -> None:
        await self.requester.request("messagesReportMessage", {
            "chatRef": chat_ref,
            "messageId": message_id,
            "reason": reason,
        })

    async def set_typing(self, chat_ref: dict[str, Any], typing: bool = True) -> None:
        await self.requester.request("chatsSetTyping", {
            "chatRef": chat_ref,
            "typing": typing,
        })

    async def typing(self, chat_ref: dict[str, Any]) -> None:
        await self.set_typing(chat_ref, True)

    async def stop_typing(self, chat_ref: dict[str, Any]) -> None:
        await self.set_typing(chat_ref, False)
