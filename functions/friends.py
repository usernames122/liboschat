from __future__ import annotations

from typing import Any

from ..httpreq import Requester


REQUEST_FRIEND = 1
ACCEPT_FRIEND = 2
REMOVE_FRIEND = 3
BLOCK = 4
UNBLOCK = 5


class FriendsAPI:
    def __init__(self, requester: Requester):
        self.requester = requester

    async def list(self) -> dict[str, Any]:
        result = await self.requester.request("friendsGetRelationships", {})
        return result["relationships"]

    async def change_relationship(self, user_ref: dict[str, Any], change: int) -> None:
        await self.requester.request("friendsChangeRelationship", {
            "user": user_ref,
            "change": change,
        })

    async def request(self, user_ref: dict[str, Any]) -> None:
        await self.change_relationship(user_ref, REQUEST_FRIEND)

    async def accept(self, user_ref: dict[str, Any]) -> None:
        await self.change_relationship(user_ref, ACCEPT_FRIEND)

    async def remove(self, user_ref: dict[str, Any]) -> None:
        await self.change_relationship(user_ref, REMOVE_FRIEND)

    async def block(self, user_ref: dict[str, Any]) -> None:
        await self.change_relationship(user_ref, BLOCK)

    async def unblock(self, user_ref: dict[str, Any]) -> None:
        await self.change_relationship(user_ref, UNBLOCK)

    async def sync(
        self,
        *,
        platform_user_id: str,
        hashed_platform_user_id: bytes,
        platform: str,
        friend_ids_hashed: list[bytes],
        community_ids_hashed: list[bytes],
        platform_user_name: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "platformUserId": platform_user_id,
            "hashedPlatformUserId": hashed_platform_user_id,
            "platform": platform,
            "friendIdsHashed": friend_ids_hashed,
            "communityIdsHashed": community_ids_hashed,
        }
        if platform_user_name is not None:
            payload["platformUserName"] = platform_user_name
        await self.requester.request("friendsSyncFriends", payload)
