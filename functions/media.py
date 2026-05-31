from __future__ import annotations

from typing import Any

from ..httpreq import Requester


class MediaAPI:
    def __init__(self, requester: Requester):
        self.requester = requester

    async def upload_file_part(self, upload_id: int, part: int, data: bytes) -> None:
        await self.requester.request("mediaUploadFilePart", {
            "uploadId": upload_id,
            "part": part,
            "data": data,
        })

    async def download_file_part(self, file_ref: dict[str, Any], offset: int, length: int) -> bytes:
        result = await self.requester.request("mediaDownloadFilePart", {
            "fileRef": file_ref,
            "offset": offset,
            "length": length,
        })
        return result["filePart"].get("data", b"")

    @staticmethod
    def media_file_ref(file_id: int) -> dict[str, Any]:
        return {"mediaFile": {"fileId": file_id}}

    @staticmethod
    def chat_photo_ref(file_id: int) -> dict[str, Any]:
        return {"chatPhoto": {"fileId": file_id}}
