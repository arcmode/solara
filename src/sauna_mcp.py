#!/usr/bin/env python3
"""MCP stdio server for the SaunaBox Solara controller.

The model can call only the five tools in this file. The server does not
accept shell commands, file paths, or controller source changes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sauna_service import (
    TEMP_MAX_F,
    TEMP_MIN_F,
    TIMER_MAX_MINUTES,
    TIMER_MIN_MINUTES,
    execute,
)

PROTOCOL = "2024-11-05"

TEMP_DESCRIPTION = (
    f"Target temperature. Use temperature_f for Fahrenheit "
    f"({TEMP_MIN_F} to {TEMP_MAX_F}). "
    "If the user gives Celsius, put the Celsius integer in temperature_c "
    "and omit temperature_f. If the user gives no unit, use Fahrenheit. "
    "Provide only one of the two temperature fields."
)

TOOLS = [
    {
        "name": "sauna_status",
        "description": (
            "Read the sauna. Returns power, target_temperature_f, and "
            "remaining_minutes. The controller does not report a measured "
            "cabin temperature. Do not invent one."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "sauna_preheat",
        "description": (
            "Turn the sauna on, set the target temperature, and set the timer. "
            "Use this only when the sauna is off. Call it once. "
            "Do not call it again if the result is unverified. "
            + TEMP_DESCRIPTION
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "temperature_f": {
                    "type": "integer",
                    "minimum": TEMP_MIN_F,
                    "maximum": TEMP_MAX_F,
                    "description": "Target in degrees Fahrenheit",
                },
                "temperature_c": {
                    "type": "integer",
                    "description": "Target in degrees Celsius. The server converts it.",
                },
                "duration_minutes": {
                    "type": "integer",
                    "minimum": TIMER_MIN_MINUTES,
                    "maximum": TIMER_MAX_MINUTES,
                    "description": "Timer in minutes. Convert hours to minutes first.",
                },
            },
            "required": ["duration_minutes"],
            "additionalProperties": False,
        },
    },
    {
        "name": "sauna_off",
        "description": "Turn the sauna off and confirm the power state.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "sauna_set_temperature",
        "description": (
            "Change the target temperature while the sauna stays on. "
            "Do not use this to turn the sauna on. " + TEMP_DESCRIPTION
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "temperature_f": {
                    "type": "integer",
                    "minimum": TEMP_MIN_F,
                    "maximum": TEMP_MAX_F,
                },
                "temperature_c": {"type": "integer"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "sauna_set_timer",
        "description": (
            f"Change the remaining timer while the sauna stays on. "
            f"duration_minutes must be from {TIMER_MIN_MINUTES} to {TIMER_MAX_MINUTES}."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "duration_minutes": {
                    "type": "integer",
                    "minimum": TIMER_MIN_MINUTES,
                    "maximum": TIMER_MAX_MINUTES,
                }
            },
            "required": ["duration_minutes"],
            "additionalProperties": False,
        },
    },
]


_framing = "ndjson"


def _send(message: dict) -> None:
    body = json.dumps(message, separators=(",", ":")).encode()
    if _framing == "lsp":
        sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
    else:
        # ZeroClaw speaks newline-delimited JSON on stdio.
        sys.stdout.buffer.write(body + b"\n")
    sys.stdout.buffer.flush()


def _read_content_length(first_line: bytes) -> dict | None:
    headers = {
        first_line.decode().split(":", 1)[0].strip().lower(): first_line.decode().split(":", 1)[1].strip()
    }
    while True:
        line = sys.stdin.buffer.readline()
        if line == b"":
            return None
        if line in (b"\r\n", b"\n"):
            break
        key, value = line.decode().split(":", 1)
        headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    payload = sys.stdin.buffer.read(length)
    if len(payload) != length:
        return None
    return json.loads(payload)


def _read_message() -> dict | None:
    global _framing
    while True:
        line = sys.stdin.buffer.readline()
        if line == b"":
            return None
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith(b"content-length:"):
            _framing = "lsp"
            return _read_content_length(line)
        _framing = "ndjson"
        return json.loads(stripped)


def _result(request_id, result: dict) -> None:
    _send({"jsonrpc": "2.0", "id": request_id, "result": result})


def _error(request_id, code: int, message: str) -> None:
    _send(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }
    )


async def _handle(message: dict) -> None:
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        return
    if method == "initialize":
        _result(
            request_id,
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "solara", "version": "1.0.0"},
            },
        )
        return
    if method == "ping":
        _result(request_id, {})
        return
    if method == "tools/list":
        _result(request_id, {"tools": TOOLS})
        return
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            _result(
                request_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "confirmed": False,
                                    "status": "rejected",
                                    "error": "arguments must be an object",
                                }
                            ),
                        }
                    ],
                    "isError": True,
                },
            )
            return
        outcome = await execute(str(name), arguments)
        _result(
            request_id,
            {
                "content": [{"type": "text", "text": json.dumps(outcome)}],
                "isError": not outcome.get("confirmed", False),
            },
        )
        return
    _error(request_id, -32601, f"Method not found: {method}")


async def serve() -> None:
    while True:
        message = _read_message()
        if message is None:
            return
        try:
            await _handle(message)
        except Exception as exc:
            request_id = message.get("id")
            if request_id is not None:
                _error(request_id, -32603, str(exc))


def main() -> None:
    import asyncio

    asyncio.run(serve())


if __name__ == "__main__":
    main()
