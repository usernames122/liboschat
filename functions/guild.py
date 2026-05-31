from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..httpreq import Requester
from .messages import Message, channel_ref


@dataclass(slots=True)
class GuildRef:
    id: int

    def channel(self, channel_id: int) -> dict[str, Any]:
        return channel_ref(self.id, channel_id)


@dataclass(slots=True)
class Guild:
    id: int
    name: str
    owner: bool
    permissions: int
    muted: bool
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Guild":
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            owner=data.get("owner", False),
            permissions=data.get("permissions", 0),
            muted=data.get("muted", False),
            raw=data,
        )


@dataclass(slots=True)
class Channel:
    id: int
    guild_id: int
    name: str
    type: int
    position: int
    parent_id: int | None
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Channel":
        return cls(
            id=data["id"],
            guild_id=data["communityId"],
            name=data.get("name", ""),
            type=data.get("type", 0),
            position=data.get("position", 0),
            parent_id=data.get("parentId"),
            raw=data,
        )


@dataclass(slots=True)
class ChannelList:
    conversations: list[dict[str, Any]]
    channels: list[Channel]
    messages: list[Message]
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChannelList":
        return cls(
            conversations=data.get("conversations", []),
            channels=[Channel.from_dict(channel) for channel in data.get("channels", [])],
            messages=[Message.from_dict(message) for message in data.get("messages", [])],
            raw=data,
        )


class GuildAPI:
    def __init__(self, requester: Requester):
        self.requester = requester

    def ref(self, guild_id: int) -> GuildRef:
        return GuildRef(guild_id)

    def channel_ref(self, guild_id: int, channel_id: int) -> dict[str, Any]:
        return channel_ref(guild_id, channel_id)

    async def list(self) -> list[Guild]:
        result = await self.requester.request("communitiesGetCommunities", {})
        return [Guild.from_dict(guild) for guild in result["communities"].get("communities", [])]

    async def get(self, guild_id: int) -> Guild | None:
        for guild in await self.list():
            if guild.id == guild_id:
                return guild
        return None

    async def get_channels(self, guild_id: int) -> ChannelList:
        result = await self.requester.request("communitiesGetChannels", {"communityId": guild_id})
        return ChannelList.from_dict(result["channels"])

    async def create(self, name: str) -> Guild | None:
        await self.requester.request("communitiesCreateCommunity", {"name": name})
        guilds = await self.list()
        return next((guild for guild in guilds if guild.name == name), None)

    async def create_channel(
        self,
        guild_id: int,
        name: str,
        *,
        type: int = 0,
        parent_id: int | None = None,
    ) -> Channel | None:
        payload: dict[str, Any] = {
            "communityId": guild_id,
            "name": name,
            "type": type,
        }
        if parent_id is not None:
            payload["parentId"] = parent_id

        await self.requester.request("communitiesCreateChannel", payload)
        channels = await self.get_channels(guild_id)
        return next((channel for channel in channels.channels if channel.name == name), None)

    async def delete_channel(self, guild_id: int, channel_id: int) -> None:
        await self.requester.request("communitiesDeleteChannel", {
            "channel": channel_ref(guild_id, channel_id),
        })

    async def edit_channel(
        self,
        guild_id: int,
        channel_id: int,
        *,
        name: str | None = None,
        position: int | None = None,
        parent_id: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {"channel": channel_ref(guild_id, channel_id)}
        if name is not None:
            payload["name"] = name
        if position is not None:
            payload["position"] = position
        if parent_id is not None:
            payload["parentId"] = parent_id
        await self.requester.request("communitiesEditChannel", payload)

    async def delete(self, guild_id: int) -> None:
        await self.requester.request("communitiesDeleteCommunity", {"communityId": guild_id})

    async def leave(self, guild_id: int) -> None:
        await self.requester.request("communitiesLeaveCommunity", {"communityId": guild_id})

    async def edit(
        self,
        guild_id: int,
        *,
        name: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {"communityId": guild_id}
        if name is not None:
            payload["name"] = name
        await self.requester.request("communitiesEditCommunity", payload)

    async def edit_default_permissions(self, guild_id: int, permissions: int) -> None:
        await self.requester.request("communitiesEditDefaultPermissions", {
            "communityId": guild_id,
            "permissions": permissions,
        })

    async def get_roles(self, guild_id: int) -> dict[str, Any]:
        result = await self.requester.request("communitiesGetRoles", {"communityId": guild_id})
        return result["communityRoles"]

    async def get_members(self, guild_id: int, member_ids: list[int]) -> dict[str, Any]:
        payload: dict[str, Any] = {"communityId": guild_id, "memberIds": member_ids}
        result = await self.requester.request("communitiesGetMembers", payload)
        return result["members"]

    async def get_channel_members(self, guild_id: int, channel_id: int) -> dict[str, Any]:
        result = await self.requester.request("communitiesGetChannelMembers", {
            "communityId": guild_id,
            "channelId": channel_id,
        })
        return result["memberList"]
