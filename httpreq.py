import asyncio
import inspect
from collections import defaultdict
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import aiohttp
from protodef import Schema

from . import dbg

OSMIUM_GATEWAY = "wss://ws-0.osmium.chat/" #

EventHandler = Callable[[dict[str, Any]], Awaitable[None] | None]


class RPCError(Exception):
    def __init__(self, error: dict[str, Any]):
        self.error = error
        message = error.get("errorMessage", "RPC request failed")
        super().__init__(message)


class UnknownRPCResult(Exception):
    def __init__(self, result: dict[str, Any]):
        self.result = result
        super().__init__("RPC result used an unknown result variant")


class Requester:
    def __init__(self):
        self.schema = Schema.from_file(Path(__file__).parent / "protodefs" / "core.protodef")
        self.session: aiohttp.ClientSession | None = None
        self.connection: aiohttp.ClientWebSocketResponse | None = None
        self._receiver_task: asyncio.Task[None] | None = None
        self._next_request_id = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._send_lock = asyncio.Lock()

    async def __get_connection(self):
        if self.session is None:
            raise Exception("Requester session not initialized. Call init() first.")
        dbg.dbg_print("Requester","Attempting to connect to Osmium server. Gateway:", OSMIUM_GATEWAY)
        connection = await self.session.ws_connect(OSMIUM_GATEWAY)
        dbg.dbg_print("Requester","Connected to Osmium server.")
        return connection


    async def init(self):
        self.session = aiohttp.ClientSession()
        dbg.dbg_print("Requester","Initialized HTTP session. Connecting to gateway.")
        self.connection = await self.__get_connection()
        self._receiver_task = asyncio.create_task(self._receive_loop())

    async def close(self):
        if self._receiver_task is not None:
            self._receiver_task.cancel()
            try:
                await self._receiver_task
            except asyncio.CancelledError:
                pass
            self._receiver_task = None

        if self.connection is not None:
            await self.connection.close()
            self.connection = None

        if self.session is not None:
            await self.session.close()
            self.session = None

        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()

    def on(self, event_name: str, handler: EventHandler | None = None):
        if handler is not None:
            self.add_event_handler(event_name, handler)
            return handler

        def decorator(func: EventHandler):
            self.add_event_handler(event_name, func)
            return func

        return decorator

    def add_event_handler(self, event_name: str, handler: EventHandler):
        self._handlers[event_name].append(handler)
    
    async def request(self, payload_name: str, payload: dict[str, Any]):
        if self.connection is None:
            raise Exception("Requester session not initialized. Call init() first.")

        request_id = self._next_id()
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future

        message = {
            "id": request_id,
            payload_name: payload,
        }
        data = self.schema.encode("Core.ClientMessage", message)

        dbg.dbg_print("Requester", "Sending RPC request:", message)
        try:
            async with self._send_lock:
                await self.connection.send_bytes(data)

            result = await future
        except Exception:
            self._pending.pop(request_id, None)
            raise
        if "error" in result:
            raise RPCError(result["error"])
        return result

    async def _receive_loop(self):
        if self.connection is None:
            raise Exception("Requester connection not initialized.")

        async for ws_message in self.connection:
            try:
                if ws_message.type == aiohttp.WSMsgType.BINARY:
                    await self._handle_server_message(ws_message.data)
                elif ws_message.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_server_message(ws_message.data.encode())
                elif ws_message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
            except Exception as exc:
                dbg.dbg_print("Requester", "Failed to handle server message:", repr(exc))
                asyncio.create_task(self._dispatch_raw("decodeError", {
                    "error": repr(exc),
                    "messageType": str(ws_message.type),
                }))

        error = self.connection.exception() if self.connection is not None else None
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error or ConnectionError("Osmium gateway connection closed."))
        self._pending.clear()

    async def _handle_server_message(self, data: bytes):
        message = self.schema.decode("Core.ServerMessage", data, include_unknown=True)
        dbg.dbg_print("Requester", "Received server message:", message)

        result = message.get("result")
        if result is not None:
            self._complete_pending_request(message, result)
            return

        update = message.get("update")
        if update is not None:
            await self._dispatch_update(update)
            return

        if "_unknown" in message:
            await self._dispatch_raw("unknownServerMessage", message)

    def _complete_pending_request(self, message: dict[str, Any], result: dict[str, Any]):
        request_id = result.get("reqId", message.get("id"))
        future = self._pending.pop(request_id, None)
        if future is None:
            dbg.dbg_print("Requester", "Received result for unknown request id:", request_id)
            return
        if not future.done():
            if self._has_unknown_result_variant(result):
                asyncio.create_task(self._dispatch_raw("unknownRPCResult", result))
            future.set_result(result)

    async def _dispatch_update(self, update: dict[str, Any]):
        event_name = next((key for key, value in update.items() if key != "_unknown" and value is not None), None)
        if event_name is None:
            dbg.dbg_print("Requester", "Received empty update:", update)
            if "_unknown" in update:
                await self._dispatch_raw("unknownUpdate", update)
            return

        handlers = [*self._handlers.get(event_name, []), *self._handlers.get("*", [])]
        for handler in handlers:
            asyncio.create_task(self._run_event_handler(handler, update[event_name]))

    async def _dispatch_raw(self, event_name: str, payload: dict[str, Any]):
        handlers = [*self._handlers.get(event_name, []), *self._handlers.get("*", [])]
        for handler in handlers:
            asyncio.create_task(self._run_event_handler(handler, payload))

    @staticmethod
    def _has_unknown_result_variant(result: dict[str, Any]) -> bool:
        return any(item.get("tag") != 37 for item in result.get("_unknown", []))

    async def _run_event_handler(self, handler: EventHandler, payload: dict[str, Any]):
        try:
            result = handler(payload)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            dbg.dbg_print("Requester", "Event handler failed:", repr(exc))

    def _next_id(self):
        request_id = self._next_request_id
        self._next_request_id += 1
        return request_id
