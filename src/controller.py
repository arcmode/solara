#!/usr/bin/env python3
"""Local, closed-loop SaunaBox Solara BLE controller.

Requires: pip install bleak

Commands:
    python solara_controller.py status
    python solara_controller.py on
    python solara_controller.py off
    python solara_controller.py set-temp 150
    python solara_controller.py set-timer 30
    python solara_controller.py start --temp 150 --minutes 30

Run heating commands only while the sauna is physically supervised.
Mac Bluetooth identifiers do not carry over to Linux; override with --device or
SOLARA_BLE_ID when moving hardware.
"""

import argparse
import asyncio
import os
import sys
import time
from dataclasses import asdict, dataclass

from bleak import BleakClient

DEFAULT_DEVICE = "2C9CEA82-8865-DFFD-3B86-33A06D4EABC4"
CHAR_FFF1 = "0000fff1-0000-1000-8000-00805f9b34fb"
KEY = {
    "power": b"AT+KEY=01\r\n",
    "temp_up": b"AT+KEY=02\r\n",
    "temp_down": b"AT+KEY=03\r\n",
    "timer_up": b"AT+KEY=04\r\n",
    "timer_down": b"AT+KEY=05\r\n",
}


@dataclass(frozen=True)
class Status:
    on: bool
    target_f: int
    minutes_left: int


def decode_status(data: bytearray | bytes) -> Status | None:
    b = bytes(data)
    if len(b) != 15 or b[:2] != b"\xff\xaa" or b[-2:] != b"\r\n":
        return None
    if (sum(b[:12]) & 0xFF) != b[12] or b[2] not in (0, 1):
        return None
    return Status(on=bool(b[2]), target_f=b[4], minutes_left=b[5])


class Solara:
    def __init__(self, device: str):
        self.client = BleakClient(device, timeout=20)
        self.queue: asyncio.Queue[Status] = asyncio.Queue(maxsize=32)
        self.latest: Status | None = None

    async def __aenter__(self):
        await self.client.connect()
        await self.client.start_notify(CHAR_FFF1, self._on_notify)
        return self

    async def __aexit__(self, *_):
        if self.client.is_connected:
            await self.client.disconnect()

    def _on_notify(self, _characteristic, payload):
        state = decode_status(payload)
        if state is None:
            return
        self.latest = state
        if self.queue.full():
            self.queue.get_nowait()
        self.queue.put_nowait(state)

    def _discard_old_notifications(self):
        while not self.queue.empty():
            self.queue.get_nowait()

    async def _until(self, predicate, timeout: float, description: str) -> Status:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Timed out waiting for {description}; latest={self.latest}")
            try:
                state = await asyncio.wait_for(self.queue.get(), remaining)
            except asyncio.TimeoutError as exc:
                raise TimeoutError(
                    f"Timed out waiting for {description}; latest={self.latest}"
                ) from exc
            if predicate(state):
                return state

    async def status(self) -> Status:
        # Require a *fresh* notification, rather than reusing a cached value.
        state = await self._until(lambda _: True, 10, "status notification")
        # The sauna briefly reports ON with a zero timer during power-on.
        if state.on and state.minutes_left == 0:
            state = await self._until(
                lambda s: not s.on or s.minutes_left > 0,
                12,
                "valid startup status",
            )
        return state

    async def _write(self, key: str):
        await self.client.write_gatt_char(CHAR_FFF1, KEY[key], response=True)

    async def set_power(self, desired: bool) -> Status:
        before = await self.status()
        if before.on == desired:
            return before
        self._discard_old_notifications()
        await self._write("power")
        return await self._until(
            lambda s: s.on == desired and (not desired or s.minutes_left > 0),
            18,
            f"power {'ON' if desired else 'OFF'} confirmation",
        )

    async def _adjust(self, field: str, target: int, lower: int, upper: int,
                      up_cmd: str, down_cmd: str) -> Status:
        if not lower <= target <= upper:
            raise ValueError(f"{field} must be between {lower} and {upper}")
        current = await self.status()
        if not current.on:
            raise RuntimeError("Sauna must be ON before changing settings")

        for step in range(120):  # hard bound: never blindly write forever
            value = getattr(current, field)
            if value == target:
                return current
            delta = 1 if target > value else -1
            expected = value + delta
            self._discard_old_notifications()
            await self._write(up_cmd if delta > 0 else down_cmd)
            # Require observation of the expected value before the next write.
            current = await self._until(
                lambda s: s.on and getattr(s, field) == expected,
                8,
                f"{field} {value} -> {expected} after step {step + 1}",
            )

        raise RuntimeError(f"Exceeded adjustment limit; latest={self.latest}")

    async def set_temp(self, fahrenheit: int) -> Status:
        return await self._adjust("target_f", fahrenheit, 77, 158,
                                  "temp_up", "temp_down")

    async def set_timer(self, minutes: int) -> Status:
        # 0 is intentionally excluded; it is not a useful heating duration.
        return await self._adjust("minutes_left", minutes, 1, 90,
                                  "timer_up", "timer_down")

    async def start(self, fahrenheit: int, minutes: int) -> Status:
        if not 77 <= fahrenheit <= 158 or not 1 <= minutes <= 90:
            raise ValueError("Allowed range: 77–158°F and 1–90 minutes")
        state = await self.status()
        if state.on:
            raise RuntimeError(
                "Already ON; use set-temp or set-timer instead of resetting a session"
            )
        await self.set_power(True)
        try:
            await self.set_temp(fahrenheit)
            return await self.set_timer(minutes)
        except Exception:
            # Best-effort safe rollback of a session we just started.
            try:
                await self.set_power(False)
            except Exception as exc:
                print(f"URGENT: Could not confirm shutdown: {exc}", file=sys.stderr)
            raise


async def run(args):
    async with Solara(args.device) as sauna:
        if args.command == "status":
            result = await sauna.status()
        elif args.command == "on":
            result = await sauna.set_power(True)
        elif args.command == "off":
            result = await sauna.set_power(False)
        elif args.command == "set-temp":
            result = await sauna.set_temp(args.fahrenheit)
        elif args.command == "set-timer":
            result = await sauna.set_timer(args.minutes)
        elif args.command == "start":
            result = await sauna.start(args.temp, args.minutes)
        else:
            raise ValueError(f"Unknown command: {args.command}")
        print(asdict(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SaunaBox Solara BLE controller")
    parser.add_argument(
        "--device",
        default=os.getenv("SOLARA_BLE_ID", DEFAULT_DEVICE),
        help="macOS CoreBluetooth UUID or Linux BLE device address",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "on", "off"):
        commands.add_parser(name)
    commands.add_parser("set-temp").add_argument("fahrenheit", type=int)
    commands.add_parser("set-timer").add_argument("minutes", type=int)
    start_parser = commands.add_parser("start")
    start_parser.add_argument("--temp", type=int, required=True)
    start_parser.add_argument("--minutes", type=int, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except (TimeoutError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
