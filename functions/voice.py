from __future__ import annotations

from typing import Any

from ..httpreq import Requester
from ..voice_connection import VoiceConnection, VoiceRoomInfo


class VoiceAPI:
    def __init__(self, requester: Requester):
        self.requester = requester

    async def request_room(self, chat_ref: dict[str, Any]) -> dict[str, Any]:
        result = await self.requester.request("voiceRequestRoom", {"chatRef": chat_ref})
        return result["roomInfo"]

    async def connect(self, chat_ref: dict[str, Any], *, user_id: int) -> VoiceConnection:
        room = VoiceRoomInfo.from_dict(await self.request_room(chat_ref))
        connection = VoiceConnection(room, user_id=user_id)
        return await connection.connect(wait_for_media=False)

    async def send_ffmpeg_voice(self, chat_ref: dict[str, Any], source: str, *, user_id: int) -> VoiceConnection:
        room = VoiceRoomInfo.from_dict(await self.request_room(chat_ref))
        connection = VoiceConnection(room, user_id=user_id)
        return await connection.connect(audio_source=source)

    async def dvr_record(self, chat_ref: dict[str, Any], out: str = "./voice.ogg", *, user_id: int) -> VoiceConnection:
        room = VoiceRoomInfo.from_dict(await self.request_room(chat_ref))
        connection = VoiceConnection(room, user_id=user_id)
        return await connection.connect(record_to=out)

    async def disconnect(self, connection: VoiceConnection) -> None:
        """Disconnect from a voice room, notifying the server first."""
        await connection.disconnect()
