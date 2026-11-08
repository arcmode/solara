import json
import os
import subprocess
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "src", "sauna_mcp.py")


def _encode(message: dict) -> bytes:
    body = json.dumps(message).encode()
    return f"Content-Length: {len(body)}\r\n\r\n".encode() + body


def _read(pipe) -> dict:
    headers = {}
    while True:
        line = pipe.readline()
        if line in (b"\r\n", b"\n"):
            break
        key, value = line.decode().split(":", 1)
        headers[key.strip().lower()] = value.strip()
    length = int(headers["content-length"])
    return json.loads(pipe.read(length))


def _run(messages: list[dict], env: dict) -> list[dict]:
    process = subprocess.Popen(
        [sys.executable, SERVER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=os.path.join(ROOT, "src"),
        env=env,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    for message in messages:
        process.stdin.write(_encode(message))
    process.stdin.close()
    replies = []
    while True:
        header = process.stdout.readline()
        if header == b"":
            break
        headers = {header.decode().split(":", 1)[0].strip().lower(): header.decode().split(":", 1)[1].strip()}
        while True:
            line = process.stdout.readline()
            if line in (b"\r\n", b"\n"):
                break
            key, value = line.decode().split(":", 1)
            headers[key.strip().lower()] = value.strip()
        replies.append(json.loads(process.stdout.read(int(headers["content-length"]))))
    stderr = process.stderr.read().decode() if process.stderr is not None else ""
    code = process.wait(timeout=10)
    assert code == 0, stderr
    return replies


def test_mcp_lists_only_sauna_tools_and_executes_fake_preheat():
    env = os.environ.copy()
    env["SOLARA_BACKEND"] = "fake"
    env["SOLARA_FAKE_STATE"] = '{"on": false, "target_f": 100, "minutes_left": 0}'
    env.pop("SOLARA_FAKE_FAIL", None)
    replies = _run(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "sauna_preheat",
                    "arguments": {"temperature_f": 150, "duration_minutes": 90},
                },
            },
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "sauna_preheat",
                    "arguments": {"temperature_f": 200, "duration_minutes": 10},
                },
            },
        ],
        env,
    )
    by_id = {item["id"]: item for item in replies}
    names = [tool["name"] for tool in by_id[2]["result"]["tools"]]
    assert names == [
        "sauna_status",
        "sauna_preheat",
        "sauna_off",
        "sauna_set_temperature",
        "sauna_set_timer",
    ]
    ok = json.loads(by_id[3]["result"]["content"][0]["text"])
    assert by_id[3]["result"]["isError"] is False
    assert ok["confirmed"] is True
    assert ok["target_temperature_f"] == 150
    assert ok["remaining_minutes"] == 90
    bad = json.loads(by_id[4]["result"]["content"][0]["text"])
    assert by_id[4]["result"]["isError"] is True
    assert bad["confirmed"] is False
    assert bad["status"] == "rejected"
