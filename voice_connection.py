from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
from dataclasses import dataclass
from typing import Any

import aiohttp


class VoiceDependencyError(RuntimeError):
    pass


def _load_aiortc():
    try:
        from aiortc import (
            RTCBundlePolicy,
            RTCConfiguration,
            RTCIceServer,
            RTCPeerConnection,
            RTCSessionDescription,
        )
        from aiortc.contrib.media import MediaPlayer, MediaRecorder
    except ModuleNotFoundError as exc:
        raise VoiceDependencyError(
            "voice media requires optional dependencies: install aiortc and av, and keep ffmpeg on PATH"
        ) from exc
    return (
        RTCPeerConnection,
        RTCSessionDescription,
        MediaPlayer,
        MediaRecorder,
        RTCConfiguration,
        RTCIceServer,
        RTCBundlePolicy,
    )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off", ""}


def _split_env_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in re.split(r"[\s,]+", value) if item.strip()]


def _voice_ice_servers(RTCIceServer) -> list[Any]:
    urls = _split_env_list(os.getenv("OSMIUM_VOICE_TURN_URLS") or os.getenv("OSMIUM_VOICE_TURN_URL"))
    if not urls:
        return []
    return [
        RTCIceServer(
            urls=urls,
            username=os.getenv("OSMIUM_VOICE_TURN_USERNAME") or None,
            credential=os.getenv("OSMIUM_VOICE_TURN_CREDENTIAL") or None,
        )
    ]


def _force_aiortc_relay_policy() -> None:
    try:
        import aioice
        import aiortc.rtcicetransport as rtcicetransport
    except ModuleNotFoundError as exc:
        raise VoiceDependencyError(
            "voice relay-only mode requires aioice; install aiortc and its dependencies"
        ) from exc

    original_connection = rtcicetransport.Connection
    if getattr(original_connection, "_osmium_relay_policy_wrapper", False):
        return

    def relay_connection(*args, **kwargs):
        kwargs["transport_policy"] = aioice.TransportPolicy.RELAY
        return original_connection(*args, **kwargs)

    relay_connection._osmium_relay_policy_wrapper = True
    rtcicetransport.Connection = relay_connection


def _peer_connection_configuration(RTCConfiguration, RTCIceServer, RTCBundlePolicy):
    relay_only = _env_bool("OSMIUM_VOICE_RELAY_ONLY", True)
    ice_servers = _voice_ice_servers(RTCIceServer)
    has_turn = any(
        url.startswith(("turn:", "turns:"))
        for server in ice_servers
        for url in (server.urls if isinstance(server.urls, list) else [server.urls])
    )
    if relay_only:
        if not has_turn:
            raise VoiceDependencyError(
                "voice relay-only mode requires OSMIUM_VOICE_TURN_URLS, plus "
                "OSMIUM_VOICE_TURN_USERNAME and OSMIUM_VOICE_TURN_CREDENTIAL if your TURN server needs auth"
            )
        _force_aiortc_relay_policy()
    return RTCConfiguration(
        iceServers=ice_servers or None,
        bundlePolicy=RTCBundlePolicy.MAX_BUNDLE,
    )


def _coerce_param(value: str) -> str | int:
    return int(value) if value.isdigit() else value


def _codecs_from_sdp(sdp: str) -> list[dict[str, Any]]:
    codecs: dict[int, dict[str, Any]] = {}
    rtx: dict[int, int] = {}
    current_kind: str | None = None

    for raw_line in sdp.splitlines():
        line = raw_line.strip()
        if line.startswith("m="):
            current_kind = line.split("=", 1)[1].split(" ", 1)[0]
            continue
        if current_kind is None:
            continue
        match = re.match(r"a=rtpmap:(\d+)\s+([^/]+)/(\d+)(?:/(\d+))?", line)
        if match:
            payload = int(match.group(1))
            name = match.group(2).lower()
            codecs[payload] = {
                "kind": current_kind,
                "name": name,
                "payloadType": payload,
                "clockRate": int(match.group(3)),
                "channels": int(match.group(4)) if match.group(4) else None,
                "rtxPayloadType": None,
                "parameters": {},
            }
            continue
        match = re.match(r"a=fmtp:(\d+)\s+(.+)", line)
        if match:
            payload = int(match.group(1))
            params = {}
            for item in match.group(2).split(";"):
                if "=" not in item:
                    continue
                key, value = item.strip().split("=", 1)
                params[key] = _coerce_param(value)
            if payload in codecs:
                codecs[payload]["parameters"] = params
            if codecs.get(payload, {}).get("name") == "rtx" and "apt" in params:
                rtx[int(params["apt"])] = payload

    out = []
    for payload, codec in codecs.items():
        if codec["name"] == "rtx":
            continue
        if codec["name"] != "opus":
            continue
        item = dict(codec)
        item["rtxPayloadType"] = rtx.get(payload)
        if item["channels"] is None:
            item.pop("channels")
        if item["rtxPayloadType"] is None:
            item.pop("rtxPayloadType")
        out.append(item)
    return out


def _extract_audio_ssrc(sdp: str) -> int | None:
    in_audio = False
    for line in sdp.splitlines():
        if line.startswith("m="):
            in_audio = line.startswith("m=audio")
        if in_audio:
            match = re.match(r"a=ssrc:(\d+)", line)
            if match:
                return int(match.group(1))
    return None


def _extract_audio_mid(sdp: str) -> str:
    in_audio = False
    for line in sdp.splitlines():
        if line.startswith("m="):
            in_audio = line.startswith("m=audio")
        if in_audio and line.startswith("a=mid:"):
            return line.split(":", 1)[1]
    return "0"


def _extract_audio_direction(sdp: str, *, has_source: bool) -> str:
    in_audio = False
    for line in sdp.splitlines():
        if line.startswith("m="):
            in_audio = line.startswith("m=audio")
        if in_audio and line in {"a=sendrecv", "a=sendonly", "a=recvonly", "a=inactive"}:
            return line[2:]
    return "sendonly" if has_source else "recvonly"


def _extract_audio_extmaps(sdp: str) -> list[tuple[str, str]]:
    allowed = {
        "urn:ietf:params:rtp-hdrext:ssrc-audio-level",
        "http://www.ietf.org/id/draft-holmer-rmcat-transport-wide-cc-extensions-01",
    }
    out: list[tuple[str, str]] = []
    in_audio = False
    for line in sdp.splitlines():
        if line.startswith("m="):
            in_audio = line.startswith("m=audio")
        if not in_audio:
            continue
        match = re.match(r"a=extmap:([^\s]+)\s+(\S+)", line)
        if match and match.group(2) in allowed:
            out.append((match.group(1), match.group(2)))
    return out


def _extract_session_lines(sdp: str) -> dict[str, str]:
    out = {"origin": "o=tngl 1337 0 IN IP4 127.0.0.1", "fingerprint": ""}
    for line in sdp.splitlines():
        if line.startswith("o="):
            out["origin"] = line
        elif line.startswith("a=fingerprint:") and not out["fingerprint"]:
            out["fingerprint"] = line
    return out


def _split_first_media(sdp: str) -> tuple[list[str], list[str]]:
    session: list[str] = []
    media: list[str] = []
    current = session
    for line in sdp.replace("\r\n", "\n").split("\n"):
        if not line:
            continue
        if line.startswith("m="):
            if media:
                break
            current = media
        current.append(line)
    return session, media


def _reverse_direction(direction: str, ssrc: int | None) -> str:
    if ssrc is None:
        return "inactive"
    return {
        "sendrecv": "sendrecv",
        "sendonly": "recvonly",
        "recvonly": "sendonly",
        "inactive": "inactive",
    }.get(direction, "inactive")


def _include_ssrcs(*, is_answer: bool, direction: str, ssrc: int | None) -> bool:
    if ssrc is None:
        return False
    is_recv = direction in {"recvonly", "sendrecv"}
    return (is_answer and is_recv) or (not is_answer and not is_recv)


def _build_media_section(
    base_sdp: str,
    *,
    local_sdp: str,
    codec: dict[str, Any],
    direction: str,
    mid: str,
    ssrc: int | None,
    extensions: list[tuple[str, str]],
    is_answer: bool,
    user_id: int,
    session_id: str | None,
) -> list[str]:
    _, base_media = _split_first_media(base_sdp)
    payload = str(codec["payloadType"])
    lines: list[str] = [f"m=audio 9 UDP/TLS/RTP/SAVPF {payload}"]
    # aiortc requires RTCP mux for WebRTC SDP.
    if not any(line == "a=rtcp-mux" for line in base_media):
        lines.append("a=rtcp-mux")
    skip_prefixes = (
        "a=rtpmap:",
        "a=fmtp:",
        "a=rtcp-fb:",
        "a=extmap:",
        "a=ssrc:",
        "a=ssrc-group:",
        "a=mid:",
        "a=msid:",
        "a=setup:",
        "a=sendrecv",
        "a=sendonly",
        "a=recvonly",
        "a=inactive",
    )
    if not is_answer:
        skip_prefixes = (*skip_prefixes, "a=candidate:")

    local_info = _extract_session_lines(local_sdp)
    for line in base_media[1:]:
        if line.startswith(skip_prefixes):
            continue
        if not is_answer and line.startswith("a=fingerprint:"):
            continue
        lines.append(line)

    if not is_answer and local_info["fingerprint"]:
        lines.append(local_info["fingerprint"])
    lines.append(f"a=setup:{'passive' if is_answer else 'actpass'}")
    lines.append(f"a=mid:{mid}")
    lines.append(f"a={_reverse_direction(direction, ssrc) if is_answer else direction}")
    msid = f"{user_id}-{session_id or '0'}-{ssrc} {ssrc}" if ssrc is not None else None
    if msid is not None:
        lines.append(f"a=msid:{msid}")
    lines.append(f"a=rtpmap:{payload} opus/48000/2")
    for ext_id, uri in extensions:
        lines.append(f"a=extmap:{ext_id} {uri}")
    lines.append(f"a=rtcp-fb:{payload} transport-cc")
    lines.append(f"a=fmtp:{payload} minptime=10;useinbandfec=1;usedtx=1")

    if _include_ssrcs(is_answer=is_answer, direction=direction, ssrc=ssrc):
        cname = f"cname-{ssrc}"
        lines.append(f"a=ssrc:{ssrc} cname:{cname}")
        if msid is not None:
            lines.append(f"a=ssrc:{ssrc} msid:{msid}")
    return lines


def _build_description(
    base_sdp: str,
    *,
    local_sdp: str,
    codec: dict[str, Any],
    direction: str,
    mid: str,
    ssrc: int | None,
    extensions: list[tuple[str, str]],
    is_answer: bool,
    user_id: int,
    session_id: str | None,
) -> str:
    local_info = _extract_session_lines(local_sdp)
    session = [
        "v=0",
        local_info["origin"] if not is_answer else "o=tngl 1337 0 IN IP4 127.0.0.1",
        "s=-",
        "t=0 0",
    ]
    if local_info["fingerprint"] and not is_answer:
        session.append(local_info["fingerprint"])
    session.append(f"a=group:BUNDLE {mid}")
    session.append("a=msid-semantic: WMS *")
    media = _build_media_section(
        base_sdp,
        local_sdp=local_sdp,
        codec=codec,
        direction=direction,
        mid=mid,
        ssrc=ssrc,
        extensions=extensions,
        is_answer=is_answer,
        user_id=user_id,
        session_id=session_id,
    )
    return "\r\n".join(session + media) + "\r\n"


def _select_audio_codec(codecs: list[dict[str, Any]] | None, local_sdp: str) -> dict[str, Any]:
    for codec in codecs or []:
        if codec.get("kind") == "audio" and codec.get("name") == "opus":
            return codec
    local = _codecs_from_sdp(local_sdp)
    if local:
        return local[0]
    return {"kind": "audio", "name": "opus", "payloadType": 111, "parameters": {}}


@dataclass(slots=True)
class VoiceRoomInfo:
    room_id: int
    endpoint: str
    token: str
    chat_ref: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VoiceRoomInfo":
        return cls(
            room_id=data["roomId"],
            endpoint=data["endpoint"],
            token=data["token"],
            chat_ref=data["chatRef"],
        )


class VoiceConnection:
    def __init__(self, room: VoiceRoomInfo, *, user_id: int):
        self.room = room
        self.user_id = user_id
        self.session: aiohttp.ClientSession | None = None
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self.pc: Any = None
        self.player: Any = None
        self.recorder: Any = None
        self.session_id: str | None = None
        self._media_error: asyncio.Future[BaseException] | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._connected = asyncio.Event()
        self._has_source = False
        self.debug = os.getenv("OSMIUM_VOICE_DEBUG") == "1"

    async def connect(
        self,
        *,
        audio_source: str | None = None,
        record_to: str | None = None,
        wait_for_media: bool | None = None,
    ) -> "VoiceConnection":
        loop = asyncio.get_running_loop()
        self._media_error = loop.create_future()
        self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(self.room.endpoint)
        (
            RTCPeerConnection,
            RTCSessionDescription,
            MediaPlayer,
            MediaRecorder,
            RTCConfiguration,
            RTCIceServer,
            RTCBundlePolicy,
        ) = _load_aiortc()
        configuration = _peer_connection_configuration(RTCConfiguration, RTCIceServer, RTCBundlePolicy)
        self.pc = RTCPeerConnection(configuration=configuration)

        if audio_source is not None:
            self._has_source = True
            self.player = MediaPlayer(audio_source)
            if self.player.audio is None:
                raise ValueError(f"ffmpeg source did not produce an audio stream: {audio_source!r}")
            transceiver = self.pc.addTransceiver("audio", direction="sendonly")
            replaced = transceiver.sender.replaceTrack(self.player.audio)
            if inspect.isawaitable(replaced):
                await replaced
        else:
            self.pc.addTransceiver("audio", direction="recvonly")

        if record_to is not None:
            self.recorder = MediaRecorder(record_to)

            @self.pc.on("track")
            async def on_track(track):
                if track.kind == "audio":
                    self.recorder.addTrack(track)
                    await self.recorder.start()

        offer = await self.pc.createOffer()
        self._reader_task = asyncio.create_task(self._read_loop(RTCSessionDescription))

        await self._send({
            "type": "prepare",
            "data": {
                "protocol": "webrtc",
                "codecs": _codecs_from_sdp(offer.sdp),
                "sdp": offer.sdp,
            },
        })
        await self._send({
            "type": "connect",
            "data": {
                "roomId": str(self.room.room_id),
                "userId": str(self.user_id),
                "token": self.room.token,
            },
        })

        if wait_for_media is None:
            wait_for_media = audio_source is not None or record_to is not None
        if wait_for_media:
            assert self._media_error is not None
            done, pending = await asyncio.wait(
                {
                    asyncio.create_task(self._connected.wait()),
                    self._media_error,
                },
                timeout=30,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if not done:
                raise TimeoutError("timed out waiting for voice media negotiation")
            result = next(iter(done)).result()
            if isinstance(result, BaseException):
                raise result
        else:
            await asyncio.wait_for(self._ready.wait(), timeout=30)
        return self

    async def wait_closed(self) -> None:
        if self._reader_task is not None:
            await self._reader_task

    async def disconnect(self) -> None:
        """Notify the server we are leaving the voice room and clean up."""
        try:
            await self._send({
                "type": "disconnect",
                "data": {"roomId": str(self.room.room_id)},
            })
        except Exception:
            pass
        await self.close()

    async def close(self) -> None:
        if self.recorder is not None:
            await self.recorder.stop()
            self.recorder = None
        if self.pc is not None:
            await self.pc.close()
            self.pc = None
        if self.ws is not None:
            await self.ws.close()
            self.ws = None
        if self.session is not None:
            await self.session.close()
            self.session = None
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None

    async def set_audio_state(self, *, muted: bool = False, deafened: bool = False) -> None:
        await self._send({
            "type": "updateAudio",
            "data": {
                "ssrc": _extract_audio_ssrc(self.pc.localDescription.sdp) if self.pc and self.pc.localDescription else None,
                "producerPaused": muted,
                "consumerPaused": deafened,
            },
        })

    async def _read_loop(self, RTCSessionDescription) -> None:
        assert self.ws is not None
        try:
            async for message in self.ws:
                if message.type != aiohttp.WSMsgType.TEXT:
                    continue
                payload = json.loads(message.data)
                await self._handle_server_message(payload, RTCSessionDescription)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._media_error is not None and not self._media_error.done():
                self._media_error.set_result(exc)
            if self.debug:
                print("[VoiceConnection] read loop failed", repr(exc))

    async def _handle_server_message(self, payload: dict[str, Any], RTCSessionDescription) -> None:
        if self.debug:
            print("[VoiceConnection] recv", json.dumps(payload, default=str)[:2000])
        kind = payload.get("type")
        data = payload.get("data") or {}
        if kind == "ready":
            self.session_id = str(data.get("sessionId"))
            self._ready.set()
            return
        if kind in {"roomConfig", "roomConfigUpdate"}:
            if RTCSessionDescription is None:
                return
            sdp = data.get("sdp")
            if sdp and self.pc is not None:
                try:
                    offer = await self.pc.createOffer()
                    local_sdp = offer.sdp
                    codec = _select_audio_codec(data.get("codecs"), local_sdp)
                    mid = _extract_audio_mid(local_sdp)
                    direction = _extract_audio_direction(local_sdp, has_source=self._has_source)
                    ssrc = _extract_audio_ssrc(local_sdp) if self._has_source else None
                    extensions = _extract_audio_extmaps(local_sdp)
                    local_offer = _build_description(
                        sdp,
                        local_sdp=local_sdp,
                        codec=codec,
                        direction=direction,
                        mid=mid,
                        ssrc=ssrc,
                        extensions=extensions,
                        is_answer=False,
                        user_id=self.user_id,
                        session_id=self.session_id,
                    )
                    remote_answer = _build_description(
                        sdp,
                        local_sdp=local_sdp,
                        codec=codec,
                        direction=direction,
                        mid=mid,
                        ssrc=ssrc,
                        extensions=extensions,
                        is_answer=True,
                        user_id=self.user_id,
                        session_id=self.session_id,
                    )
                    if self.debug:
                        print("[VoiceConnection] local offer", local_offer[:2000])
                        print("[VoiceConnection] remote answer", remote_answer[:2000])
                    await self.pc.setLocalDescription(RTCSessionDescription(sdp=local_offer, type="offer"))
                    await self.pc.setRemoteDescription(RTCSessionDescription(sdp=remote_answer, type="answer"))
                    if ssrc is not None:
                        await self._send({"type": "updateAudio", "data": {"ssrc": ssrc}})
                    await self.set_audio_state(muted=not self._has_source, deafened=False)
                    self._connected.set()
                except Exception as exc:
                    if self._media_error is not None and not self._media_error.done():
                        self._media_error.set_result(exc)
                    if self.debug:
                        print("[VoiceConnection] setRemoteDescription failed", repr(exc))
            return
        if kind == "updateAudio":
            return
        if kind == "clientConnected":
            return
        if kind == "clientDisconnected":
            return

    async def _send(self, payload: dict[str, Any]) -> None:
        if self.ws is None:
            raise RuntimeError("voice websocket is not connected")
        if self.debug:
            print("[VoiceConnection] send", json.dumps(payload, default=str)[:2000])
        await self.ws.send_str(json.dumps(payload))
