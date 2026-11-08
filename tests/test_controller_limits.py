import pytest

from controller import Solara, decode_status


def _frame(power: int, target: int, minutes: int) -> bytes:
    body = bytearray(15)
    body[0] = 0xFF
    body[1] = 0xAA
    body[2] = power
    body[4] = target
    body[5] = minutes
    body[12] = sum(body[:12]) & 0xFF
    body[13] = 0x0D
    body[14] = 0x0A
    return bytes(body)


def test_decode_status_reads_target_and_timer():
    state = decode_status(_frame(1, 150, 90))
    assert state is not None
    assert state.on is True
    assert state.target_f == 150
    assert state.minutes_left == 90


def test_decode_status_rejects_bad_frames():
    assert decode_status(b"") is None
    bad = bytearray(_frame(1, 150, 90))
    bad[12] ^= 0xFF
    assert decode_status(bad) is None
    assert decode_status(_frame(2, 150, 90)) is None


@pytest.mark.asyncio
async def test_controller_rejects_limits_before_connect():
    sauna = Solara("00:00:00:00:00:00")
    with pytest.raises(ValueError):
        await sauna.set_temp(160)
    with pytest.raises(ValueError):
        await sauna.set_temp(76)
    with pytest.raises(ValueError):
        await sauna.set_timer(0)
    with pytest.raises(ValueError):
        await sauna.set_timer(91)
    with pytest.raises(ValueError):
        await sauna.start(150, 0)
    assert sauna.client.is_connected is False
