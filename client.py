from __future__ import annotations

from typing import Any

from .functions import (
    AccountAPI,
    Authorization,
    BillingAPI,
    ChatsAPI,
    FriendsAPI,
    GuildAPI,
    MediaAPI,
    MessagesAPI,
    ReactionsAPI,
    SettingsAPI,
    StickersAPI,
    VoiceAPI,
)
from .functions.messages import user_ref
from .httpreq import Requester


DEFAULT_CLIENT_INFO = {
    "clientId": 120715,
    "deviceType": "Linux",
    "deviceVersion": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "appVersion": "1779586403603",
    "noSubscribe": False,
}


class Client:
    def __init__(self, *, client_info: dict[str, Any] | None = None):
        self.requester = Requester()
        self.client_info = {**DEFAULT_CLIENT_INFO, **(client_info or {})}
        self.account = AccountAPI(self.requester)
        self.messages = MessagesAPI(self.requester)
        self.guilds = GuildAPI(self.requester)
        self.chats = ChatsAPI(self.requester)
        self.friends = FriendsAPI(self.requester)
        self.media = MediaAPI(self.requester)
        self.reactions = ReactionsAPI(self.requester)
        self.settings = SettingsAPI(self.requester)
        self.stickers = StickersAPI(self.requester)
        self.billing = BillingAPI(self.requester)
        self.voice = VoiceAPI(self.requester)
        self.initialized: dict[str, Any] | None = None
        self.authorization: Authorization | None = None
        self._auth_token: str | None = None
        self.requester.add_reconnect_handler(self._restore_session_after_reconnect)

    async def connect(self):
        await self.requester.init()
        result = await self.requester.request("coreInitialize", self.client_info)
        self.initialized = result.get("initialized")
        return self.initialized

    async def close(self):
        await self.requester.close()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    def on(self, event_name, handler=None):
        return self.requester.on(event_name, handler)

    async def request(self, payload_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.requester.request(payload_name, payload)

    def _require_user_id(self) -> int:
        if self.authorization is None:
            raise ValueError("voice requires a logged-in client")
        user_id = self.authorization.user.get("id")
        if user_id is None:
            raise ValueError("authorization user has no id")
        return user_id

    async def send_ffmpeg_voice(self, chat_ref: dict[str, Any], source: str):
        return await self.voice.send_ffmpeg_voice(chat_ref, source, user_id=self._require_user_id())

    async def dvr_record(self, chat_ref: dict[str, Any], out: str = "./voice.ogg"):
        return await self.voice.dvr_record(chat_ref, out, user_id=self._require_user_id())

    async def login_as_guest(self, guest_uname: str | None = None):
        self.authorization = await self.account.login_as_guest(guest_uname)
        self._auth_token = self.authorization.token
        return self.authorization

    async def sign_in(self, email: str, password: str, *, totp: str | None = None):
        self.authorization = await self.account.sign_in(email, password, totp=totp)
        self._auth_token = self.authorization.token
        return self.authorization

    async def login_with_token(self, token: str):
        self.authorization = await self.account.login_with_token(token)
        self._auth_token = self.authorization.token
        return self.authorization

    async def _restore_session_after_reconnect(self):
        result = await self.requester.request("coreInitialize", self.client_info)
        self.initialized = result.get("initialized")
        if self._auth_token is None:
            return
        result = await self.requester.request("authAuthorize", {"token": self._auth_token})
        self.authorization = Authorization.from_dict(result["authorization"])
        self._auth_token = self.authorization.token

    async def verify_email(self, email: str, code: str):
        return await self.account.verify_email(email, code)

    async def resend_email_verification(self, email: str | None = None):
        return await self.account.resend_email_verification(email)

    async def lock_in_username(self, username: str | None = None) -> str:
        if username is None:
            if self.authorization is None:
                raise ValueError("username is required before logging in")
            username = self.authorization.user.get("username") or self.authorization.user.get("name")
            if not username:
                raise ValueError("could not infer username from authorization user")
        await self.account.lock_in_username(username)
        return username

    async def lookup_username(self, username: str) -> dict[str, Any]:
        result = await self.requester.request("usersLookupUsername", {
            "username": username,
        })
        return result["userDetails"]["user"]

    async def send_dm(self, username: str, content: str) -> int:
        target = await self.lookup_username(username)
        return await self.messages.send(user_ref(target["id"]), content)
