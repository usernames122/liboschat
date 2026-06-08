from __future__ import annotations

import io
import mimetypes
import secrets
from pathlib import Path
from typing import Any, BinaryIO

from ..httpreq import Requester


UPLOAD_PART_SIZE = 512 * 1024
DOWNLOAD_PART_SIZE = 512 * 1024


class MediaAPI:
    def __init__(self, requester: Requester):
        self.requester = requester

    async def upload(
        self,
        data: bytes | bytearray | memoryview,
        *,
        filename: str | None = None,
        mimetype: str | None = None,
        metadata: dict[str, Any] | None = None,
        part_size: int = UPLOAD_PART_SIZE,
    ) -> dict[str, Any]:
        return await self.upload_fp(
            io.BytesIO(data),
            filename=filename,
            mimetype=mimetype,
            metadata=metadata,
            part_size=part_size,
        )

    async def upload_fp(
        self,
        fp: BinaryIO,
        *,
        filename: str | None = None,
        mimetype: str | None = None,
        metadata: dict[str, Any] | None = None,
        part_size: int = UPLOAD_PART_SIZE,
    ) -> dict[str, Any]:
        if part_size <= 0:
            raise ValueError("part_size must be greater than 0")

        fp_name = getattr(fp, "name", "file")
        filename = filename or Path(fp_name if isinstance(fp_name, str) else "file").name or "file"
        mimetype = mimetype or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        if metadata is None:
            metadata = {"file": {}}

        upload_id = secrets.randbits(63)
        part_count = 0

        while True:
            chunk = fp.read(part_size)
            if not chunk:
                break
            await self.upload_file_part(upload_id, part_count, bytes(chunk))
            part_count += 1

        if part_count == 0:
            await self.upload_file_part(upload_id, 0, b"")
            part_count = 1

        return {
            "uploaded": {
                "file": {
                    "id": upload_id,
                    "name": filename,
                    "partCount": part_count,
                },
                "filename": filename,
                "mimetype": mimetype,
                "metadata": metadata,
            }
        }

    async def download(
        self,
        file_ref: dict[str, Any],
        length: int,
        *,
        part_size: int = DOWNLOAD_PART_SIZE,
    ) -> bytes:
        fp = io.BytesIO()
        await self.download_fp(file_ref, fp, length, part_size=part_size)
        return fp.getvalue()

    async def download_fp(
        self,
        file_ref: dict[str, Any],
        fp: BinaryIO,
        length: int,
        *,
        part_size: int = DOWNLOAD_PART_SIZE,
    ) -> int:
        if length < 0:
            raise ValueError("length must be greater than or equal to 0")
        if part_size <= 0:
            raise ValueError("part_size must be greater than 0")

        written = 0
        while written < length:
            chunk_size = min(part_size, length - written)
            data = await self.download_file_part(file_ref, written, chunk_size)
            if not data:
                break
            fp.write(data)
            written += len(data)
        return written

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
