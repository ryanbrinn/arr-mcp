"""Unix socket HTTP server for arr-helper."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import stat
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from arr_helper.handlers import HANDLERS

log = logging.getLogger(__name__)

# Default socket path — overridden by HELPER_SOCKET env var
DEFAULT_SOCKET = "/run/arr-helper/arr-helper.sock"


def _socket_path() -> str:
    return os.environ.get("HELPER_SOCKET", DEFAULT_SOCKET)


def _json_response(data: dict[str, Any]) -> bytes:
    body = json.dumps(data).encode()
    headers = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: application/json\r\n"
        b"Connection: close\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n"
    )
    return headers + body


def _error_response(status: int, message: str) -> bytes:
    body = json.dumps({"ok": False, "error": message, "exit_code": 1}).encode()
    status_line = f"HTTP/1.1 {status} Error\r\n".encode()
    headers = (
        status_line
        + b"Content-Type: application/json\r\n"
        + b"Connection: close\r\n"
        + b"Content-Length: "
        + str(len(body)).encode()
        + b"\r\n\r\n"
    )
    return headers + body


async def _handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """Handle a single HTTP request over the Unix socket."""
    try:
        raw = await asyncio.wait_for(reader.read(65536), timeout=10.0)
        if not raw:
            return

        # Parse the minimal HTTP envelope — we only accept POST /command
        try:
            header_section, _, body_bytes = raw.partition(b"\r\n\r\n")
            request_line = header_section.split(b"\r\n")[0].decode()
            method, path, _ = request_line.split(" ", 2)
        except Exception:
            writer.write(_error_response(400, "Malformed request"))
            await writer.drain()
            return

        if method != "POST" or path != "/command":
            writer.write(_error_response(404, f"Unknown endpoint: {method} {path}"))
            await writer.drain()
            return

        try:
            payload = json.loads(body_bytes)
            op = str(payload.get("op", ""))
            args: dict[str, str] = {k: str(v) for k, v in payload.get("args", {}).items()}
        except (json.JSONDecodeError, AttributeError):
            writer.write(_error_response(400, "Invalid JSON body"))
            await writer.drain()
            return

        handler: Callable[..., Coroutine[Any, Any, tuple[int, str]]] | None = HANDLERS.get(op)  # type: ignore[assignment]
        if handler is None:
            writer.write(_error_response(400, f"Unknown op: {op!r}"))
            await writer.drain()
            return

        log.info("op=%s args=%s", op, {k: v for k, v in args.items() if k != "content"})

        try:
            exit_code, output = await handler(args)
        except ValueError as exc:
            writer.write(_error_response(400, str(exc)))
            await writer.drain()
            return
        except Exception as exc:
            log.exception("Handler error for op=%s", op)
            writer.write(_error_response(500, f"Internal error: {exc}"))
            await writer.drain()
            return

        response_data: dict[str, Any] = {
            "ok": exit_code == 0,
            "output": output,
            "exit_code": exit_code,
        }
        writer.write(_json_response(response_data))
        await writer.drain()

    finally:
        writer.close()


def _make_socket_dir(socket_path: str) -> None:
    """Create socket directory with restrictive permissions."""
    directory = Path(socket_path).parent
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(stat.S_IRWXU)  # 0700


async def serve(socket_path: str | None = None) -> None:
    """Start the Unix socket server."""
    path = socket_path or _socket_path()
    _make_socket_dir(path)

    # Remove stale socket
    sock = Path(path)
    if sock.exists():
        sock.unlink()

    server = await asyncio.start_unix_server(_handle_connection, path=path)

    # Restrict socket to owner only (0600)
    sock.chmod(stat.S_IRUSR | stat.S_IWUSR)

    log.info("arr-helper listening on %s", path)
    async with server:
        await server.serve_forever()
