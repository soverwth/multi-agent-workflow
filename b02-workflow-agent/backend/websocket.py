from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import threading
import time
from typing import BinaryIO

WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_CLIENT_MESSAGE = 1_000_000


def websocket_accept(client_key: str) -> str:
    """Return the RFC 6455 Sec-WebSocket-Accept value."""
    digest = hashlib.sha1((client_key + WEBSOCKET_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def encode_frame(payload: bytes = b"", opcode: int = 0x1) -> bytes:
    """Encode one unmasked server-to-client WebSocket frame."""
    first = 0x80 | opcode
    length = len(payload)
    if length < 126:
        header = bytes((first, length))
    elif length <= 65_535:
        header = bytes((first, 126)) + struct.pack("!H", length)
    else:
        header = bytes((first, 127)) + struct.pack("!Q", length)
    return header + payload


def read_frame(reader: BinaryIO) -> tuple[int, bytes]:
    """Read a complete, non-fragmented client frame from the HTTP buffer."""
    header = reader.read(2)
    if len(header) != 2:
        raise ConnectionError("WebSocket 连接已关闭。")
    first, second = header
    if not first & 0x80:
        raise ConnectionError("暂不支持分片 WebSocket 消息。")
    opcode = first & 0x0F
    masked = bool(second & 0x80)
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", reader.read(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", reader.read(8))[0]
    if length > MAX_CLIENT_MESSAGE:
        raise ConnectionError("WebSocket 客户端消息过大。")
    if not masked:
        raise ConnectionError("客户端 WebSocket 帧必须掩码。")
    mask = reader.read(4)
    payload = reader.read(length)
    if len(mask) != 4 or len(payload) != length:
        raise ConnectionError("WebSocket 帧不完整。")
    return opcode, bytes(value ^ mask[index % 4] for index, value in enumerate(payload))


class WebSocketClient:
    def __init__(self, connection: socket.socket, reader: BinaryIO):
        self.connection = connection
        self.reader = reader
        self._write_lock = threading.Lock()

    def send_frame(self, payload: bytes = b"", opcode: int = 0x1) -> None:
        with self._write_lock:
            self.connection.sendall(encode_frame(payload, opcode))

    def send_json(self, value: dict) -> None:
        self.send_frame(json.dumps(value, ensure_ascii=False).encode("utf-8"))


class WorkflowEventHub:
    """In-process fan-out of B02 events; clients never mutate the blackboard."""

    def __init__(self):
        self._clients: dict[str, set[WebSocketClient]] = {}
        self._lock = threading.RLock()

    def register(self, run_id: str, client: WebSocketClient) -> None:
        with self._lock:
            self._clients.setdefault(run_id, set()).add(client)

    def unregister(self, run_id: str, client: WebSocketClient) -> None:
        with self._lock:
            clients = self._clients.get(run_id)
            if not clients:
                return
            clients.discard(client)
            if not clients:
                self._clients.pop(run_id, None)

    def publish(self, run: dict, event: dict) -> None:
        message = {"type": "event", "run_id": run["run_id"], "sequence": event["sequence"], "event": event, "run": run}
        with self._lock:
            clients = list(self._clients.get(run["run_id"], set()))
        for client in clients:
            try:
                client.send_json(message)
            except (ConnectionError, OSError):
                self.unregister(run["run_id"], client)

    def client_count(self, run_id: str) -> int:
        with self._lock:
            return len(self._clients.get(run_id, set()))


def serve_websocket(client: WebSocketClient, hub: WorkflowEventHub, run: dict) -> None:
    """Send an initial snapshot, then stream events until the peer disconnects."""
    run_id = run["run_id"]
    hub.register(run_id, client)
    try:
        client.send_json({"type": "snapshot", "run_id": run_id, "sequence": len(run["events"]), "run": run})
        client.connection.settimeout(1.0)
        last_ping = time.monotonic()
        while True:
            if time.monotonic() - last_ping >= 20:
                client.send_frame(b"B02", 0x9)
                last_ping = time.monotonic()
            try:
                opcode, payload = read_frame(client.reader)
            except socket.timeout:
                continue
            if opcode == 0x8:
                try:
                    client.send_frame(payload[:125], 0x8)
                except OSError:
                    pass
                break
            if opcode == 0x9:
                client.send_frame(payload[:125], 0xA)
            elif opcode == 0x1:
                message = json.loads(payload.decode("utf-8"))
                if message.get("type") == "ping":
                    client.send_json({"type": "pong", "run_id": run_id, "time": time.time()})
    except (ConnectionError, OSError, ValueError, json.JSONDecodeError):
        pass
    finally:
        hub.unregister(run_id, client)
