"""Validated sauna operations for the local agent.

The BLE controller reports the target temperature and the remaining time.
It does not report a measured cabin temperature.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

TEMP_MIN_F = 77
TEMP_MAX_F = 158
TIMER_MIN_MINUTES = 1
TIMER_MAX_MINUTES = 90


@dataclass(frozen=True)
class DeviceState:
    on: bool
    target_f: int
    minutes_left: int


class SaunaPort(Protocol):
    async def status(self) -> DeviceState: ...

    async def set_power(self, desired: bool) -> DeviceState: ...

    async def set_temp(self, fahrenheit: int) -> DeviceState: ...

    async def set_timer(self, minutes: int) -> DeviceState: ...

    async def start(self, fahrenheit: int, minutes: int) -> DeviceState: ...


def _state_fields(state: DeviceState) -> dict:
    return {
        "power": "on" if state.on else "off",
        "target_temperature_f": state.target_f,
        "remaining_minutes": state.minutes_left,
    }


def confirmed(state: DeviceState) -> dict:
    return {"confirmed": True, "status": "confirmed", **_state_fields(state)}


def failure(kind: str, message: str, state: DeviceState | None = None) -> dict:
    body = {"confirmed": False, "status": kind, "error": message}
    if state is not None:
        body.update(_state_fields(state))
    return body


def require_int(value: object, name: str) -> int:
    if isinstance(value, bool) or isinstance(value, str):
        raise ValueError(f"{name} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ValueError(f"{name} must be an integer")


def require_minutes(value: object) -> int:
    minutes = require_int(value, "duration_minutes")
    if minutes < TIMER_MIN_MINUTES or minutes > TIMER_MAX_MINUTES:
        raise ValueError(
            f"duration_minutes must be from {TIMER_MIN_MINUTES} to {TIMER_MAX_MINUTES}"
        )
    return minutes


def celsius_to_fahrenheit(celsius: int) -> int:
    return round(celsius * 9 / 5 + 32)


def resolve_temperature(
    temperature_f: object = None,
    temperature_c: object = None,
) -> int:
    """Return one Fahrenheit target. Reject values outside the heater limits."""
    has_f = temperature_f is not None
    has_c = temperature_c is not None
    if has_f == has_c:
        raise ValueError("Provide temperature_f or temperature_c, not both")
    if has_c:
        celsius = require_int(temperature_c, "temperature_c")
        fahrenheit = celsius_to_fahrenheit(celsius)
    else:
        fahrenheit = require_int(temperature_f, "temperature_f")
    if fahrenheit < TEMP_MIN_F or fahrenheit > TEMP_MAX_F:
        raise ValueError(
            f"temperature must be from {TEMP_MIN_F} to {TEMP_MAX_F} degrees Fahrenheit"
        )
    return fahrenheit


async def _call(operation) -> dict:
    try:
        state = await operation()
    except ValueError as exc:
        return failure("rejected", str(exc))
    except TimeoutError as exc:
        return failure("unverified", str(exc))
    except RuntimeError as exc:
        return failure("failed", str(exc))
    except Exception as exc:
        return failure("failed", f"{type(exc).__name__}: {exc}")
    return confirmed(state)


async def sauna_status(port: SaunaPort) -> dict:
    return await _call(port.status)


async def sauna_preheat(
    port: SaunaPort,
    duration_minutes: object,
    temperature_f: object = None,
    temperature_c: object = None,
) -> dict:
    fahrenheit = resolve_temperature(temperature_f, temperature_c)
    minutes = require_minutes(duration_minutes)
    return await _call(lambda: port.start(fahrenheit, minutes))


async def sauna_off(port: SaunaPort) -> dict:
    return await _call(lambda: port.set_power(False))


async def sauna_set_temperature(
    port: SaunaPort,
    temperature_f: object = None,
    temperature_c: object = None,
) -> dict:
    fahrenheit = resolve_temperature(temperature_f, temperature_c)
    return await _call(lambda: port.set_temp(fahrenheit))


async def sauna_set_timer(port: SaunaPort, duration_minutes: object) -> dict:
    minutes = require_minutes(duration_minutes)
    return await _call(lambda: port.set_timer(minutes))


class SolaraPort:
    """One BLE session around the existing controller."""

    def __init__(self, device: str):
        self.device = device
        self._context = None
        self._sauna = None

    async def __aenter__(self) -> "SolaraPort":
        from controller import Solara

        self._context = Solara(self.device)
        self._sauna = await self._context.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._context is not None:
            await self._context.__aexit__(exc_type, exc, tb)

    def _unwrap(self, state) -> DeviceState:
        return DeviceState(
            on=bool(state.on),
            target_f=int(state.target_f),
            minutes_left=int(state.minutes_left),
        )

    async def status(self) -> DeviceState:
        return self._unwrap(await self._sauna.status())

    async def set_power(self, desired: bool) -> DeviceState:
        return self._unwrap(await self._sauna.set_power(desired))

    async def set_temp(self, fahrenheit: int) -> DeviceState:
        return self._unwrap(await self._sauna.set_temp(fahrenheit))

    async def set_timer(self, minutes: int) -> DeviceState:
        return self._unwrap(await self._sauna.set_timer(minutes))

    async def start(self, fahrenheit: int, minutes: int) -> DeviceState:
        return self._unwrap(await self._sauna.start(fahrenheit, minutes))


class FakePort:
    """In-memory controller with the same safety rules as the BLE controller."""

    def __init__(
        self,
        on: bool = False,
        target_f: int = 100,
        minutes_left: int = 0,
        fail: str | None = None,
    ):
        self.on = on
        self.target_f = target_f
        self.minutes_left = minutes_left
        self.fail = fail
        self.writes: list[tuple] = []

    def _state(self) -> DeviceState:
        return DeviceState(self.on, self.target_f, self.minutes_left)

    def _maybe_fail(self, stage: str) -> None:
        if self.fail == "missing" and stage == "connect":
            raise ConnectionError("Sauna BLE device was not found")
        if self.fail == "disconnect" and stage == "connect":
            raise ConnectionError("BLE connection failed")
        if self.fail == "timeout" and stage == "after_write":
            raise TimeoutError("Timed out waiting for confirmation")

    async def status(self) -> DeviceState:
        self._maybe_fail("connect")
        return self._state()

    async def set_power(self, desired: bool) -> DeviceState:
        self._maybe_fail("connect")
        if self.on == desired:
            return self._state()
        self.writes.append(("power", desired))
        self._maybe_fail("after_write")
        self.on = desired
        if desired and self.minutes_left == 0:
            self.minutes_left = 1
        return self._state()

    async def set_temp(self, fahrenheit: int) -> DeviceState:
        self._maybe_fail("connect")
        if not TEMP_MIN_F <= fahrenheit <= TEMP_MAX_F:
            raise ValueError(
                f"target_f must be between {TEMP_MIN_F} and {TEMP_MAX_F}"
            )
        if not self.on:
            raise RuntimeError("Sauna must be ON before changing settings")
        if self.target_f != fahrenheit:
            self.writes.append(("temp", fahrenheit))
            self._maybe_fail("after_write")
            self.target_f = fahrenheit
        return self._state()

    async def set_timer(self, minutes: int) -> DeviceState:
        self._maybe_fail("connect")
        if not TIMER_MIN_MINUTES <= minutes <= TIMER_MAX_MINUTES:
            raise ValueError(
                f"minutes_left must be between {TIMER_MIN_MINUTES} and {TIMER_MAX_MINUTES}"
            )
        if not self.on:
            raise RuntimeError("Sauna must be ON before changing settings")
        if self.minutes_left != minutes:
            self.writes.append(("timer", minutes))
            self._maybe_fail("after_write")
            self.minutes_left = minutes
        return self._state()

    async def start(self, fahrenheit: int, minutes: int) -> DeviceState:
        if not TEMP_MIN_F <= fahrenheit <= TEMP_MAX_F or not (
            TIMER_MIN_MINUTES <= minutes <= TIMER_MAX_MINUTES
        ):
            raise ValueError("Allowed range: 77–158°F and 1–90 minutes")
        if self.on:
            raise RuntimeError(
                "Already ON; use set-temp or set-timer instead of resetting a session"
            )
        await self.set_power(True)
        try:
            await self.set_temp(fahrenheit)
            return await self.set_timer(minutes)
        except Exception:
            try:
                await self.set_power(False)
            except Exception:
                pass
            raise


def live_device_id() -> str:
    from controller import DEFAULT_DEVICE

    return os.environ.get("SOLARA_BLE_ID", DEFAULT_DEVICE)


def fake_from_env() -> FakePort:
    import json

    raw = os.environ.get("SOLARA_FAKE_STATE", "")
    data = json.loads(raw) if raw else {}
    fail = os.environ.get("SOLARA_FAKE_FAIL") or data.get("fail")
    return FakePort(
        on=bool(data.get("on", False)),
        target_f=int(data.get("target_f", 100)),
        minutes_left=int(data.get("minutes_left", 0)),
        fail=fail or None,
    )


class Backend:
    def __init__(self, port: SaunaPort):
        self.port = port

    async def __aenter__(self) -> SaunaPort:
        enter = getattr(self.port, "__aenter__", None)
        if enter is not None:
            await enter()
        return self.port

    async def __aexit__(self, exc_type, exc, tb) -> None:
        exit_ = getattr(self.port, "__aexit__", None)
        if exit_ is not None:
            await exit_(exc_type, exc, tb)


def open_backend() -> Backend:
    backend = os.environ.get("SOLARA_BACKEND", "live")
    if backend == "fake":
        return Backend(fake_from_env())
    if backend != "live":
        raise RuntimeError(f"Unknown SOLARA_BACKEND {backend}")
    return Backend(SolaraPort(live_device_id()))


OPERATIONS = {
    "sauna_status": sauna_status,
    "sauna_preheat": sauna_preheat,
    "sauna_off": sauna_off,
    "sauna_set_temperature": sauna_set_temperature,
    "sauna_set_timer": sauna_set_timer,
}

ARGUMENT_KEYS = {
    "sauna_status": set(),
    "sauna_preheat": {"temperature_f", "temperature_c", "duration_minutes"},
    "sauna_off": set(),
    "sauna_set_temperature": {"temperature_f", "temperature_c"},
    "sauna_set_timer": {"duration_minutes"},
}


async def execute(name: str, arguments: dict | None = None) -> dict:
    """Run one named operation. Validate arguments before BLE connect."""
    if name not in OPERATIONS:
        return failure("rejected", f"Unknown operation {name}")
    arguments = dict(arguments or {})
    unknown = set(arguments) - ARGUMENT_KEYS[name]
    if unknown:
        return failure("rejected", f"Unknown arguments: {', '.join(sorted(unknown))}")
    try:
        if name == "sauna_preheat":
            resolve_temperature(
                arguments.get("temperature_f"), arguments.get("temperature_c")
            )
            require_minutes(arguments.get("duration_minutes"))
        elif name == "sauna_set_temperature":
            resolve_temperature(
                arguments.get("temperature_f"), arguments.get("temperature_c")
            )
        elif name == "sauna_set_timer":
            require_minutes(arguments.get("duration_minutes"))
    except ValueError as exc:
        return failure("rejected", str(exc))

    try:
        async with open_backend() as port:
            return await OPERATIONS[name](port, **arguments)
    except ValueError as exc:
        return failure("rejected", str(exc))
    except TimeoutError as exc:
        return failure("unverified", str(exc))
    except Exception as exc:
        return failure("failed", f"{type(exc).__name__}: {exc}")
