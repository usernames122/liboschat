from __future__ import annotations

from typing import Any

from ..httpreq import Requester


class ChatsAPI:
    def __init__(self, requester: Requester):
        self.requester = requester

    async def list(
        self,
        *,
        limit: int | None = None,
        max_id: int | None = None,
        min_id: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if limit is not None:
            payload["limit"] = limit
        if max_id is not None:
            payload["maxId"] = max_id
        if min_id is not None:
            payload["minId"] = min_id
        result = await self.requester.request("chatsGetChats", payload)
        return result["chats"]

    async def get(self, chat_ref: dict[str, Any]) -> dict[str, Any]:
        result = await self.requester.request("chatsGetChat", {"chatRef": chat_ref})
        return result["chat"]

    async def create(self, users: list[dict[str, Any]], name: str) -> dict[str, Any]:
        result = await self.requester.request("chatsCreateChat", {
            "users": users,
            "name": name,
        })
        return result["group"]

    async def update(self, chat_ref: dict[str, Any], *, name: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"chatRef": chat_ref}
        if name is not None:
            payload["name"] = name
        result = await self.requester.request("chatsUpdateChat", payload)
        return result["chat"]

    async def remove_member(self, chat_ref: dict[str, Any], user_id: int) -> None:
        await self.requester.request("chatsRemoveChatMember", {
            "chatRef": chat_ref,
            "userId": user_id,
        })

    async def mark_read(self, chat_ref: dict[str, Any], message_id: int, *, read_amount: int | None = None) -> None:
        payload: dict[str, Any] = {
            "chatRef": chat_ref,
            "messageId": message_id,
        }
        if read_amount is not None:
            payload["readAmount"] = read_amount
        await self.requester.request("chatsMarkChatRead", payload)

    async def create_invite(
        self,
        chat_ref: dict[str, Any],
        *,
        expires_at: int | None = None,
        max_uses: int | None = None,
    ) -> str:
        payload: dict[str, Any] = {"chatRef": chat_ref}
        if expires_at is not None:
            payload["expiresAt"] = expires_at
        if max_uses is not None:
            payload["maxUses"] = max_uses
        result = await self.requester.request("chatsCreateChatInvite", payload)
        return result["createdInvite"]["code"]

    async def list_invites(self, chat_ref: dict[str, Any]) -> list[dict[str, Any]]:
        result = await self.requester.request("chatsListChatInvites", {"chatRef": chat_ref})
        return result["inviteList"].get("invites", [])

    async def delete_invite(self, code: str) -> None:
        await self.requester.request("chatsDeleteChatInvite", {"code": code})
