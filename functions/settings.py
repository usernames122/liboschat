from __future__ import annotations

from pathlib import Path
from typing import Any, BinaryIO

from ..httpreq import Requester
from .media import MediaAPI, UPLOAD_PART_SIZE


STATUS_ONLINE = 0
STATUS_IDLE = 1

NOTIF_ALL = 0
NOTIF_MENTIONS = 1
NOTIF_NONE = 2


class SettingsAPI:
    def __init__(self, requester: Requester):
        self.requester = requester

    async def get_account(self) -> dict[str, Any]:
        result = await self.requester.request("settingsGetAccount", {})
        return result["account"]

    async def edit_profile(
        self,
        *,
        name: str | None = None,
        username: str | None = None,
        bio: str | None = None,
        icon: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if username is not None:
            payload["username"] = username
        if bio is not None:
            payload["bio"] = bio
        if icon is not None:
            payload["icon"] = icon
        await self.requester.request("settingsEditProfile", payload)

    async def edit_profile_photo(self, file: dict[str, Any] | None = None) -> None:
        payload: dict[str, Any] = {}
        if file is not None:
            payload["file"] = file
        await self.requester.request("settingsEditProfilePhoto", payload)

    async def set_profile_file(
        self,
        file: str | Path | bytes | bytearray | memoryview | BinaryIO,
        *,
        filename: str | None = None,
        mimetype: str | None = None,
        part_size: int = UPLOAD_PART_SIZE,
    ) -> dict[str, Any]:
        media = MediaAPI(self.requester)

        if isinstance(file, str | Path):
            path = Path(file)
            with path.open("rb") as fp:
                uploaded = await media.upload_fp(
                    fp,
                    filename=filename or path.name,
                    mimetype=mimetype,
                    metadata={"image": {}},
                    part_size=part_size,
                )
        elif isinstance(file, bytes | bytearray | memoryview):
            uploaded = await media.upload(
                file,
                filename=filename,
                mimetype=mimetype,
                metadata={"image": {}},
                part_size=part_size,
            )
        else:
            uploaded = await media.upload_fp(
                file,
                filename=filename,
                mimetype=mimetype,
                metadata={"image": {}},
                part_size=part_size,
            )

        uploaded_file = uploaded["uploaded"]["file"]
        await self.edit_profile_photo(uploaded_file)
        return uploaded_file

    async def change_status(self, status: int = STATUS_ONLINE, activities: list[dict[str, Any]] | None = None) -> None:
        await self.requester.request("settingsChangeStatus", {
            "status": status,
            "activities": activities or [],
        })

    async def change_notification_preferences(
        self,
        prefs: int,
        *,
        chat_ref: dict[str, Any] | None = None,
        community_id: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {"prefs": prefs}
        if chat_ref is not None:
            payload["chatRef"] = chat_ref
        if community_id is not None:
            payload["communityId"] = community_id
        await self.requester.request("settingsChangeNotificationPreferences", payload)

    async def change_password(self, current_password: str, new_password: str, *, revoke_sessions: bool = True) -> None:
        await self.requester.request("settingsChangePassword", {
            "currentPassword": current_password,
            "newPassword": new_password,
            "revokeSessions": revoke_sessions,
        })

    async def change_email(self, new_email: str) -> None:
        await self.requester.request("settingsChangeEmail", {"newEmail": new_email})

    async def setup_totp(self, enabled: bool, code: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"enabled": enabled}
        if code is not None:
            payload["code"] = code
        result = await self.requester.request("settingsSetupTotp", payload)
        return result["totp"]

    async def register_web_push(self, endpoint: str, p256dh: str, auth: str) -> None:
        await self.requester.request("settingsRegisterPushSubscription", {
            "web": {
                "endpoint": endpoint,
                "p256dh": p256dh,
                "auth": auth,
            },
        })

    async def unregister_push(self) -> None:
        await self.requester.request("settingsUnregisterPushSubscription", {})
