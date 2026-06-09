import asyncio
import inspect
import os
from contextvars import ContextVar
from collections import defaultdict
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import aiohttp
from protodef import Schema

from . import dbg

OSMIUM_GATEWAY = "wss://ws-0.osmium.chat/" #
RPC_TIMEOUT_SECONDS = float(os.getenv("OSMIUM_RPC_TIMEOUT_SECONDS", "30"))
RECONNECT_INITIAL_DELAY_SECONDS = float(os.getenv("OSMIUM_RECONNECT_INITIAL_DELAY_SECONDS", "1"))
RECONNECT_MAX_DELAY_SECONDS = float(os.getenv("OSMIUM_RECONNECT_MAX_DELAY_SECONDS", "30"))

EventHandler = Callable[[dict[str, Any]], Awaitable[None] | None]
ReconnectHandler = Callable[[], Awaitable[None] | None]
_BYPASS_READY = ContextVar("liboschat_requester_bypass_ready", default=False)


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
        self._reconnect_handlers: list[ReconnectHandler] = []
        self._send_lock = asyncio.Lock()
        self._socket_connected = asyncio.Event()
        self._ready = asyncio.Event()
        self._closed = False

    async def __get_connection(self):
        if self.session is None:
            raise Exception("Requester session not initialized. Call init() first.")
        dbg.dbg_print("Requester","Attempting to connect to Osmium server. Gateway:", OSMIUM_GATEWAY)
        connection = await self.session.ws_connect(OSMIUM_GATEWAY)
        dbg.dbg_print("Requester","Connected to Osmium server.")
        return connection


    async def init(self):
        self._closed = False
        self.session = aiohttp.ClientSession()
        dbg.dbg_print("Requester","Initialized HTTP session. Connecting to gateway.")
        self.connection = await self.__get_connection()
        self._socket_connected.set()
        self._ready.set()
        self._receiver_task = asyncio.create_task(self._receive_loop())

    async def close(self):
        self._closed = True
        self._socket_connected.clear()
        self._ready.clear()

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

    def add_reconnect_handler(self, handler: ReconnectHandler):
        self._reconnect_handlers.append(handler)
    
    async def request(self, payload_name: str, payload: dict[str, Any]):
        if self.session is None:
            raise Exception("Requester session not initialized. Call init() first.")

        if _BYPASS_READY.get():
            await self._socket_connected.wait()
        else:
            await self._ready.wait()

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
                if self.connection is None or self.connection.closed:
                    raise ConnectionError("Osmium gateway connection closed.")
                await self.connection.send_bytes(data)

            timeout = RPC_TIMEOUT_SECONDS if RPC_TIMEOUT_SECONDS > 0 else None
            result = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.CancelledError:
            self._pending.pop(request_id, None)
            raise
        except Exception:
            self._pending.pop(request_id, None)
            raise
        if "error" in result:
            raise RPCError(result["error"])
        return result

    async def _receive_loop(self):
        reader_task: asyncio.Task[tuple[aiohttp.ClientWebSocketResponse, BaseException | None]] | None = None
        try:
            while not self._closed:
                if self.connection is None:
                    reader_task = await self._reconnect_until_ready()
                else:
                    reader_task = asyncio.create_task(self._read_connection(self.connection))

                connection, error = await reader_task
                reader_task = None
                await self._handle_connection_lost(connection, error)
        finally:
            if reader_task is not None:
                reader_task.cancel()
                try:
                    await reader_task
                except asyncio.CancelledError:
                    pass
                except Exception as exc:
                    dbg.dbg_print("Requester", "Reader task failed while stopping:", repr(exc))

    async def _read_connection(self, connection: aiohttp.ClientWebSocketResponse):
        try:
            async for ws_message in connection:
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
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            dbg.dbg_print("Requester", "Gateway read failed:", repr(exc))
            return connection, exc
        return connection, connection.exception()

    async def _handle_connection_lost(
        self,
        connection: aiohttp.ClientWebSocketResponse,
        error: BaseException | None,
    ):
        if self.connection is connection:
            self.connection = None
        self._socket_connected.clear()
        self._ready.clear()

        for future in self._pending.values():
            if not future.done():
                future.set_exception(error or ConnectionError("Osmium gateway connection closed."))
        self._pending.clear()

        if not self._closed:
            await self._dispatch_raw("gatewayDisconnected", {
                "error": repr(error) if error is not None else None,
            })

    async def _reconnect_until_ready(self):
        attempt = 0
        delay = max(RECONNECT_INITIAL_DELAY_SECONDS, 0)
        max_delay = max(RECONNECT_MAX_DELAY_SECONDS, delay)

        while not self._closed:
            attempt += 1
            reader_task: asyncio.Task[tuple[aiohttp.ClientWebSocketResponse, BaseException | None]] | None = None
            try:
                self.connection = await self.__get_connection()
                self._socket_connected.set()
                reader_task = asyncio.create_task(self._read_connection(self.connection))

                reconnect_task = asyncio.create_task(self._run_reconnect_handlers())
                done, _ = await asyncio.wait(
                    {reader_task, reconnect_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if reader_task in done:
                    connection, error = await reader_task
                    if not reconnect_task.done():
                        reconnect_task.cancel()
                        try:
                            await reconnect_task
                        except asyncio.CancelledError:
                            pass
                    else:
                        try:
                            await reconnect_task
                        except Exception as exc:
                            dbg.dbg_print("Requester", "Reconnect handler failed after socket closed:", repr(exc))
                    await self._handle_connection_lost(connection, error)
                    raise error or ConnectionError("Osmium gateway connection closed during reconnect.")

                await reconnect_task
                self._ready.set()
                await self._dispatch_raw("gatewayReconnected", {"attempt": attempt})
                return reader_task
            except Exception as exc:
                dbg.dbg_print("Requester", "Reconnect attempt failed:", repr(exc))
                await self._dispatch_raw("gatewayReconnectFailed", {
                    "attempt": attempt,
                    "delay": delay,
                    "error": repr(exc),
                })

                if self.connection is not None:
                    await self.connection.close()
                    self.connection = None
                if reader_task is not None:
                    if not reader_task.done():
                        reader_task.cancel()
                    try:
                        await reader_task
                    except asyncio.CancelledError:
                        pass
                    except Exception as reader_exc:
                        dbg.dbg_print("Requester", "Reader task failed during reconnect cleanup:", repr(reader_exc))
                self._socket_connected.clear()
                self._ready.clear()

                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(exc)
                self._pending.clear()

                if delay > 0:
                    await asyncio.sleep(delay)
                delay = min(max(delay * 2, 1), max_delay)

        raise asyncio.CancelledError

    async def _run_reconnect_handlers(self):
        token = _BYPASS_READY.set(True)
        try:
            for handler in self._reconnect_handlers:
                result = handler()
                if inspect.isawaitable(result):
                    await result
        finally:
            _BYPASS_READY.reset(token)

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
