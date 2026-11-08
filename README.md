# Sauna tools

This repository controls one SaunaBox Solara heater over Bluetooth. It contains the heater protocol, the validated operations, and the heater skill text.

The controller accepts 77°F to 158°F and 1 to 90 minutes. The tools reject values outside those limits. The tools do not accept shell commands or file paths.

The controller reports the target temperature. It does not report a measured cabin temperature. A successful result has `"confirmed": true`. A timeout has `"status": "unverified"`.

## Parts

| Part | Role | Location |
| --- | --- | --- |
| BLE controller | Heater protocol and command line | `src/controller.py` |
| Operations | Limit checks and result text | `src/sauna_service.py` |
| MCP server | The five tool operations | `src/sauna_mcp.py` |
| Skill | Heater rules for a caller | `skills/sauna/SKILL.md` |

## Tools

| Tool | Action |
| --- | --- |
| `sauna_status` | Read power, target temperature, and remaining minutes |
| `sauna_preheat` | Turn the heater on, set the temperature, and set the timer |
| `sauna_off` | Turn the heater off |
| `sauna_set_temperature` | Change the target temperature while the heater is on |
| `sauna_set_timer` | Change the remaining time while the heater is on |

`sauna_preheat` uses `Solara.start()`. That method does not send a second power command when the heater is already on.

## Heater address

Set `SOLARA_BLE_ID`, or pass `--device`, to select the heater. The default address in `controller.py` is a macOS identifier. This repository does not store the address of a heater.

## Commands

Install the project, then run a controller command:

```bash
cd ~/code/solara
uv sync
uv run python src/controller.py status
uv run python src/controller.py set-temp 150
uv run python src/controller.py set-timer 30
uv run python src/controller.py start --temp 150 --minutes 30
uv run python src/controller.py off
```

`src/sauna_mcp.py` speaks MCP over standard input and standard output. Set `SOLARA_BACKEND=fake` to run the tools without the heater. Set `SOLARA_BACKEND=live` to use Bluetooth.

## Bluetooth

Confirm the adapter is on:

```bash
bluetoothctl show
```

`Powered: yes` is required. A missing heater returns `confirmed: false` and `status: failed`. After an `unverified` result, read the status before you send the same power command again.

## Tests

```bash
cd ~/code/solara
uv run pytest -q
```

The tests cover the temperature limits, Celsius conversion, timer limits, a rejected command, an unverified timeout, a missing heater, and the MCP tool list.
