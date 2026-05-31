from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import dbg
from ..httpreq import Requester

import random


@dataclass(slots=True)
class Authorization:
    token: str
    user: dict[str, Any]
    session_id: int
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Authorization":
        return cls(
            token=data["token"],
            user=data["user"],
            session_id=data["sessionId"],
            raw=data,
        )


class AccountAPI:
    def __init__(self, requester: Requester):
        self.requester = requester

    async def sign_in(self, email: str, password: str, *, totp: str | None = None) -> Authorization:
        payload = {
            "email": email,
            "password": password,
        }
        if totp is not None:
            payload["totp"] = totp

        result = await self.requester.request("authSignIn", payload)
        return Authorization.from_dict(result["authorization"])

    async def sign_up(
        self,
        name: str,
        password: str | None = None,
        *,
        email: str | None = None,
    ) -> Authorization:
        payload = {"name": name}
        if email is not None:
            payload["email"] = email
        if password is not None:
            payload["password"] = password

        result = await self.requester.request("authSignUp", payload)
        return Authorization.from_dict(result["authorization"])
    
    async def login_as_guest(self, guest_uname: str | None = None) -> Authorization:
        # do a blank authsignup with no password or email, and a random name with a "Guest" prefix. Selfishly assuming that this will work and not cause any issues with the server
        # (havent tested if the server allows this, but it seems to be the case given that the protobuf schema has email and password as optional fields)
        random_suffix = random.randbytes(6).hex()
        guest_name = f"Guest{random_suffix}"
        if guest_uname is not None:
            guest_name = guest_uname # allow specifying a custom guest username for testing purposes, since the random one can be a bit unwieldy to work with in tests
            # and also that you dont want to create a million guest accounts when running tests repeatedly
            # (guest accounts do infact show up in the user creation logs on the server, so this is a good way to avoid spamming those logs with random guest accounts)
        else:
            dbg.dbg_print(
                "Account",
                "WARNING: You might've popped up on the signup list! This is bad.",
                "Guest username:",
                guest_name,
            )
        return await self.sign_up(guest_name)

    async def login_with_token(self, token: str) -> Authorization:
        result = await self.requester.request("authAuthorize", {"token": token})
        return Authorization.from_dict(result["authorization"])

    async def verify_email(self, email: str, code: str) -> dict[str, Any]:
        return await self.requester.request("authVerifyEmail", {
            "email": email,
            "code": code,
        })

    async def resend_email_verification(self, email: str | None = None) -> dict[str, Any]:
        payload = {}
        if email is not None:
            payload["email"] = email
        return await self.requester.request("authResendEmailVerification", payload)

    async def lock_in_username(self, username: str) -> None:
        await self.requester.request("settingsEditProfile", {"username": username})

    async def get_sessions(self) -> dict[str, Any]:
        result = await self.requester.request("authGetSessions", {})
        return result["sessions"]

    async def revoke_sessions(self, session_ids: list[int]) -> None:
        await self.requester.request("authRevokeSessions", {"sessionIds": session_ids})

    async def lookup_invite(self, code: str) -> dict[str, Any]:
        result = await self.requester.request("authLookupInvite", {"code": code})
        return result["invitePreview"]

    async def use_invite(self, code: str) -> None:
        await self.requester.request("authUseInvite", {"code": code})

    async def request_password_reset(self, email: str) -> dict[str, Any]:
        return await self.requester.request("authResetPassword", {
            "email": email,
        })

    async def confirm_password_reset(self, email: str, code: str, new_password: str) -> dict[str, Any]:
        return await self.requester.request("authResetPassword", {
            "email": email,
            "confirm": {
                "code": code,
                "newPassword": new_password,
            },
        })

    signin = sign_in
    signup = sign_up
    authorize = login_with_token
    resend_verification_email = resend_email_verification
