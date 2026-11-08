import pytest

from sauna_service import (
    FakePort,
    celsius_to_fahrenheit,
    execute,
    resolve_temperature,
)


@pytest.fixture
def fake_env(monkeypatch):
    monkeypatch.setenv("SOLARA_BACKEND", "fake")
    monkeypatch.setenv(
        "SOLARA_FAKE_STATE",
        '{"on": false, "target_f": 100, "minutes_left": 0}',
    )
    monkeypatch.delenv("SOLARA_FAKE_FAIL", raising=False)


def test_celsius_conversion_uses_standard_rounding():
    assert celsius_to_fahrenheit(65) == 149
    assert celsius_to_fahrenheit(70) == 158
    assert celsius_to_fahrenheit(0) == 32


def test_temperature_limits():
    assert resolve_temperature(temperature_f=77) == 77
    assert resolve_temperature(temperature_f=158) == 158
    assert resolve_temperature(temperature_f=150.0) == 150
    assert resolve_temperature(temperature_c=70) == 158
    with pytest.raises(ValueError):
        resolve_temperature(temperature_f=160)
    with pytest.raises(ValueError):
        resolve_temperature(temperature_f=76)
    with pytest.raises(ValueError):
        resolve_temperature(temperature_c=71)
    with pytest.raises(ValueError):
        resolve_temperature(temperature_f=150.5)
    with pytest.raises(ValueError):
        resolve_temperature(temperature_f=True)
    with pytest.raises(ValueError):
        resolve_temperature(temperature_f=150, temperature_c=65)
    with pytest.raises(ValueError):
        resolve_temperature()


@pytest.mark.asyncio
async def test_preheat_confirms_target_and_timer(fake_env):
    result = await execute(
        "sauna_preheat",
        {"temperature_f": 150, "duration_minutes": 90},
    )
    assert result["confirmed"] is True
    assert result["power"] == "on"
    assert result["target_temperature_f"] == 150
    assert result["remaining_minutes"] == 90
    assert "temperature_f" not in result


@pytest.mark.asyncio
async def test_preheat_converts_celsius(fake_env):
    result = await execute(
        "sauna_preheat",
        {"temperature_c": 65, "duration_minutes": 45},
    )
    assert result["confirmed"] is True
    assert result["target_temperature_f"] == 149
    assert result["remaining_minutes"] == 45


@pytest.mark.asyncio
async def test_preheat_rejects_unsupported_values_without_power(fake_env):
    too_hot = await execute(
        "sauna_preheat",
        {"temperature_f": 160, "duration_minutes": 90},
    )
    too_long = await execute(
        "sauna_preheat",
        {"temperature_f": 150, "duration_minutes": 91},
    )
    assert too_hot["status"] == "rejected"
    assert too_hot["confirmed"] is False
    assert too_long["status"] == "rejected"


@pytest.mark.asyncio
async def test_preheat_does_not_send_power_when_already_on(monkeypatch):
    port = FakePort(on=True, target_f=140, minutes_left=20)
    monkeypatch.setenv("SOLARA_BACKEND", "fake")

    async def preset():
        return port

    monkeypatch.setattr("sauna_service.open_backend", lambda: _Ready(port))
    result = await execute(
        "sauna_preheat",
        {"temperature_f": 150, "duration_minutes": 30},
    )
    assert result["confirmed"] is False
    assert result["status"] == "failed"
    assert port.writes == []


@pytest.mark.asyncio
async def test_off_is_idempotent(monkeypatch):
    port = FakePort(on=False, target_f=100, minutes_left=0)
    monkeypatch.setattr("sauna_service.open_backend", lambda: _Ready(port))
    result = await execute("sauna_off", {})
    assert result["confirmed"] is True
    assert result["power"] == "off"
    assert port.writes == []


@pytest.mark.asyncio
async def test_set_temperature_requires_power(monkeypatch):
    port = FakePort(on=False, target_f=100, minutes_left=0)
    monkeypatch.setattr("sauna_service.open_backend", lambda: _Ready(port))
    result = await execute("sauna_set_temperature", {"temperature_f": 150})
    assert result["status"] == "failed"
    assert port.writes == []


@pytest.mark.asyncio
async def test_set_temperature_and_timer_keep_other_fields(monkeypatch):
    port = FakePort(on=True, target_f=140, minutes_left=20)
    monkeypatch.setattr("sauna_service.open_backend", lambda: _Ready(port))
    temp = await execute("sauna_set_temperature", {"temperature_f": 155})
    timer = await execute("sauna_set_timer", {"duration_minutes": 45})
    assert temp["target_temperature_f"] == 155
    assert temp["remaining_minutes"] == 20
    assert timer["remaining_minutes"] == 45
    assert timer["target_temperature_f"] == 155


@pytest.mark.asyncio
async def test_timeout_is_unverified(monkeypatch):
    port = FakePort(on=False, target_f=100, minutes_left=0, fail="timeout")
    monkeypatch.setattr("sauna_service.open_backend", lambda: _Ready(port))
    result = await execute(
        "sauna_preheat",
        {"temperature_f": 150, "duration_minutes": 30},
    )
    assert result["confirmed"] is False
    assert result["status"] == "unverified"
    assert port.writes == [("power", True)]


@pytest.mark.asyncio
async def test_missing_device_is_failed(fake_env, monkeypatch):
    monkeypatch.setenv("SOLARA_FAKE_FAIL", "missing")
    result = await execute("sauna_status", {})
    assert result["confirmed"] is False
    assert result["status"] == "failed"
    assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_unknown_arguments_are_rejected(fake_env):
    result = await execute("sauna_off", {"command": "rm -rf /"})
    assert result["status"] == "rejected"


class _Ready:
    def __init__(self, port):
        self.port = port

    async def __aenter__(self):
        return self.port

    async def __aexit__(self, exc_type, exc, tb):
        return None
