from __future__ import annotations

from typing import Any

from ..httpreq import Requester


def unicode_emoji(value: str) -> dict[str, Any]:
    return {"unicodeEmoji": value}


class ReactionsAPI:
    def __init__(self, requester: Requester):
        self.requester = requester

    async def add(self, chat_ref: dict[str, Any], message_id: int, emoji: str | dict[str, Any]) -> None:
        await self.requester.request("reactionsAddReaction", {
            "chatRef": chat_ref,
            "messageId": message_id,
            "emoji": unicode_emoji(emoji) if isinstance(emoji, str) else emoji,
        })

    async def remove(self, chat_ref: dict[str, Any], message_id: int, emoji: str | dict[str, Any]) -> None:
        await self.requester.request("reactionsRemoveReaction", {
            "chatRef": chat_ref,
            "messageId": message_id,
            "emoji": unicode_emoji(emoji) if isinstance(emoji, str) else emoji,
        })
