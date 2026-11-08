# Sauna tools

This repository holds the SaunaBox Solara tools. The Telegram bot workspace is `~/code/home-agent`. ZeroClaw reads the bot identity and the shell rules from that repository. It loads the sauna skill through a symlink to `skills/sauna` in this repository.

You send a Telegram message. ZeroClaw reads the message. Ollama runs Qwen3.5 4B on the NVIDIA GPU. A Python tool sends the command to the SaunaBox Solara controller.

The agent does not use a hosted language model.

## Architecture

| Part | Role | Location |
| --- | --- | --- |
| Home agent | Bot workspace | `~/code/home-agent` |
| Ollama 0.40.15 | Local model server | `~/.local/bin/ollama` |
| Qwen3.5 4B | Language model | `~/.ollama/models` |
| ZeroClaw 0.8.7 | Agent and Telegram channel | `~/.local/bin/zeroclaw` |
| Sauna tools | Validated operations | `src/sauna_mcp.py` |
| Sauna skill | Heater rules for the model | `skills/sauna/SKILL.md` |
| BLE controller | Heater protocol | `src/controller.py` |

Ollama listens on `127.0.0.1:11434`. ZeroClaw calls the native Ollama `/api/chat` API. The gateway listens on `127.0.0.1:42617`.

The sauna tool is a local MCP program. A WASM plugin cannot open Bluetooth. The MCP program can call the existing controller.

The controller accepts 77°F to 158°F and 1 to 90 minutes. The tool rejects values outside those limits. The tool does not accept shell commands or file paths.

## Services

Ollama and ZeroClaw are user services. They start at login. They stop at logout until you enable lingering.

Enable lingering once. This command needs your password:

```bash
sudo loginctl enable-linger "$USER"
```

### Ollama

```bash
systemctl --user start ollama
systemctl --user stop ollama
systemctl --user restart ollama
systemctl --user status ollama
journalctl --user -u ollama -n 50
```

### ZeroClaw

```bash
zeroclaw service start
zeroclaw service stop
zeroclaw service restart
zeroclaw service status
zeroclaw service logs --lines 100
zeroclaw doctor
```

The command `zeroclaw service restart` stops the daemon and starts it again.

## GPU check

Run a short request, then read the process table:

```bash
ollama ps
nvidia-smi
```

`PROCESSOR` must show `100% GPU`. A CPU value means part of the model left the GPU.

The selected context is 8192 tokens. At that context the model uses about 3.4 GB. The RTX 3070 has 8 GB. Ollama cloud is off (`OLLAMA_NO_CLOUD=1`).

## Telegram

The Telegram channel is enabled. The authorized numeric user ID is `793763558`. The bot token is stored encrypted in the ZeroClaw config.

1. Open Telegram and talk to `@BotFather`.
2. Send `/newbot`.
3. Choose a name and a username that ends in `bot`.
4. Copy the token. Do not put the token in a file in this repository.
5. Send `/setjoingroups` to `@BotFather` and choose Disable. This stops people from adding the bot to a group.
6. On this laptop, store the token:

```bash
zeroclaw config set channels.telegram.home.bot_token
zeroclaw config set channels.telegram.home.enabled true
zeroclaw service restart
```

`config set` asks for the token and stores it encrypted.

7. Open `@mytrwn_bot` and press Start. Until you do that, Telegram has no chat for your account and the bot cannot send you a message. Then send a sauna request.

Your numeric user ID is already authorized. Only that ID can command the bot. A message from another account is rejected. If you must authorize a new ID before the first start, the service log shows a one-time code. Send this message to the bot:

```text
/bind CODE
```

You can also authorize an ID before the first start:

```bash
zeroclaw channel bind-telegram 123456789 --alias home
```

Replace `123456789` with your numeric ID. You can read that ID from `@userinfobot`.

Group messages are not a supported control path. Keep the bot out of groups. `mention_only` is also true.

The bot uses outbound long polling. You do not need a public address or a webhook.

## Sauna tools

The model can call only these operations:

| Tool | Controller action |
| --- | --- |
| `sauna_status` | Read power, target temperature, and remaining minutes |
| `sauna_preheat` | Turn the heater on, set the temperature, and set the timer |
| `sauna_off` | Turn the heater off |
| `sauna_set_temperature` | Change the target temperature while the heater is on |
| `sauna_set_timer` | Change the remaining time while the heater is on |

The controller reports the target temperature. It does not report a measured cabin temperature. A successful result has `"confirmed": true`. A timeout has `"status": "unverified"`. The model must not claim success in that case.

`sauna_preheat` uses `Solara.start()`. That method does not send a second power command when the heater is already on.

The Linux BLE address of the heater named `SAUNA-BLE` is `45:DB:0C:2B:88:B6`. The live ZeroClaw config passes it as `SOLARA_BLE_ID`. The default address in `controller.py` is a macOS identifier. On Linux, set `SOLARA_BLE_ID` or pass `--device`.

Heater rules for the model are in `skills/sauna/SKILL.md`. The bot identity and the shell rules are in `~/code/home-agent`.

## Diagnosis

**The model answer is empty.** Run `ollama ps`. Restart Ollama if the processor is not `100% GPU`. Then run `zeroclaw doctor`.

**A tool call does not run.** Read the trace:

```bash
tail -n 40 ~/.zeroclaw/data/state/runtime-trace.jsonl
```

Look for `MCP server solara connected`. If the line says `timed out`, the Python program did not answer. Test it with:

```bash
cd ~/code/solara
uv run pytest -q
```

**Bluetooth fails.** Confirm the adapter is on:

```bash
bluetoothctl show
```

`Powered: yes` is required. A missing heater returns `confirmed: false` and `status: failed`. Do not send the power command again after an `unverified` result. Read the status first.

**The gateway is open to the network.** `ss -ltnp | grep 42617` must show `127.0.0.1` only.

## Tests

```bash
cd ~/code/solara
uv run pytest -q
```

Software tests cover the temperature limits, Celsius conversion, timer limits, a rejected command, an unverified timeout, a missing heater, and the MCP tool list.

## Results

These checks passed on this laptop:

- Ollama 0.40.15 answers on `127.0.0.1:11434`.
- `qwen3.5:4b` runs at context 8192 with `100% GPU` and no CPU offload.
- A native Ollama tool call returned `add(2, 3)`.
- ZeroClaw uses only `ollama.local`. No hosted model is configured.
- The gateway listens on `127.0.0.1:42617` and stays up after `zeroclaw service restart`.
- `uv run pytest -q` passed 16 tests.
- The model called `sauna_preheat` with 150°F and 90 minutes on a fake heater.
- The model converted 65°C to 149°F.
- The model refused 160°F and did not call a tool.
- A real status read returned heater off, target 158°F, and 90 minutes.

These checks still need you:

- Create the Telegram bot and provide the token.
- Send `/bind` or provide your numeric Telegram user ID.
- Run `sudo loginctl enable-linger "$USER"` if the agent must stay up after logout.
- Approve a live heat test before anyone turns the heater on from the bot.
