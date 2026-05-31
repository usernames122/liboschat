from __future__ import annotations

from typing import Any

from ..httpreq import Requester


class StickersAPI:
    def __init__(self, requester: Requester):
        self.requester = requester

    async def saved(self, *, since: int | None = None) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {}
        if since is not None:
            payload["since"] = since
        result = await self.requester.request("stickersGetSavedStickers", payload)
        return result["savedStickers"].get("savedPacks", [])

    async def get_files(self, sticker_ids: list[int]) -> list[dict[str, Any]]:
        result = await self.requester.request("stickersGetStickerFiles", {"stickerIds": sticker_ids})
        return result["files"].get("files", [])

    async def get_pack(self, pack: dict[str, Any]) -> dict[str, Any]:
        result = await self.requester.request("stickersGetStickerPack", {"pack": pack})
        return result["stickerPack"]

    async def add_to_pack(self, pack: dict[str, Any], sticker: dict[str, Any]) -> None:
        await self.requester.request("stickersAddStickerToPack", {
            "pack": pack,
            "sticker": sticker,
        })

    async def remove_from_pack(self, pack: dict[str, Any], sticker_id: int) -> None:
        await self.requester.request("stickersRemoveStickerFromPack", {
            "pack": pack,
            "stickerId": sticker_id,
        })
