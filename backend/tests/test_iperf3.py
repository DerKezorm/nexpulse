"""Die iperf3-Quelle: Auswertung der Ausgabe, ohne einen Server zu befragen.

Die Zeilen stammen aus einem echten Lauf von iperf3 3.18 mit ``--json-stream``,
die Zahlen darin sind Beispielwerte.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from app.services.engines import iperf3
from app.services.engines.base import MeasurementError, Reporter

START = {
    "event": "start",
    "data": {"version": "iperf 3.18", "test_start": {"protocol": "TCP", "num_streams": 4, "reverse": 1}},
}
INTERVAL = {"event": "interval", "data": {"sum": {"start": 1.0, "end": 2.0, "bits_per_second": 618_000_000.0}}}
END = {
    "event": "end",
    "data": {
        "streams": [
            {
                "sender": {
                    "socket": 5,
                    "bits_per_second": 41_000_000.0,
                    "min_rtt": 18_000,
                    "mean_rtt": 24_000,
                    "max_rtt": 39_000,
                    "sender": True,
                },
                "receiver": {"socket": 5, "bits_per_second": 40_900_000.0, "sender": True},
            }
        ],
        "sum_sent": {"bytes": 52_000_000, "bits_per_second": 41_000_000.0, "sender": True},
        "sum_received": {"bytes": 51_500_000, "bits_per_second": 40_600_000.0, "sender": True},
    },
}
BUSY = {"event": "error", "data": "the server is busy running a test. try again later"}
REFUSED = {"event": "error", "data": "unable to connect to server: Connection refused"}


def lines(*events: dict[str, Any]) -> list[bytes]:
    return [(json.dumps(event) + "\n").encode() for event in events]


class FakeStdout:
    def __init__(self, output: list[bytes]) -> None:
        self.output = list(output)

    async def readline(self) -> bytes:
        return self.output.pop(0) if self.output else b""


class FakeStderr:
    def __init__(self, text: bytes = b"") -> None:
        self.text = text

    async def read(self) -> bytes:
        return self.text


class FakeProcess:
    def __init__(self, output: list[bytes], returncode: int = 0, stderr: bytes = b"") -> None:
        self.stdout = FakeStdout(output)
        self.stderr = FakeStderr(stderr)
        self.returncode = returncode
        self.killed = False
        self.args: list[str] = []

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return self.returncode


def fake_run(monkeypatch: pytest.MonkeyPatch, process: FakeProcess) -> FakeProcess:
    async def create(program: str, *args: str, **_kwargs: Any) -> FakeProcess:
        process.args = list(args)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    return process


def reporter(events: list[dict[str, object]]) -> Reporter:
    return Reporter(emit=events.append)


def test_targets_keep_their_id_and_get_the_default_port() -> None:
    targets = iperf3.parse_targets(
        [
            {"name": "VPS", "host": "vps.example.com"},
            {"name": "Home", "host": "203.0.113.9", "port": 5202},
            {"name": "broken"},
        ]
    )
    assert [target.port for target in targets] == [iperf3.DEFAULT_PORT, 5202]
    assert targets[0].id == iperf3.target_id("vps.example.com", iperf3.DEFAULT_PORT)
    # Ein anderer Port ist ein anderes Ziel.
    assert iperf3.target_id("vps.example.com", 5201) != iperf3.target_id("vps.example.com", 5202)


def test_result_counts_what_arrived() -> None:
    # sum_sent zaehlt auch, was noch im Puffer steckt. Gemessen wird, was ankam.
    mbps, byte_count = iperf3.received(END["data"])
    assert mbps == pytest.approx(40.6)
    assert byte_count == 51_500_000


def test_loaded_latency_comes_in_microseconds() -> None:
    assert iperf3.sender_rtt_ms(END["data"]) == pytest.approx(24.0)


def test_no_loaded_latency_in_the_download() -> None:
    # Bei -R sendet die Gegenstelle. Ihre RTT steht nicht in der Ausgabe des Clients, dort sind Nullen.
    reverse = {"streams": [{"sender": {"mean_rtt": 0, "sender": False}, "receiver": {"sender": False}}]}
    assert iperf3.sender_rtt_ms(reverse) is None
    # ``sender: false`` heisst: Das sind nicht unsere Zahlen. Auch wenn dort eine steht.
    remote = {"streams": [{"sender": {"mean_rtt": 30_000, "sender": False}}]}
    assert iperf3.sender_rtt_ms(remote) is None


def test_a_busy_server_is_its_own_error() -> None:
    assert iperf3.error_code(str(BUSY["data"])) == "iperf3_busy"
    assert iperf3.error_code(str(REFUSED["data"])) == "iperf3_failed"


def test_arguments_carry_the_direction_and_the_warmup() -> None:
    target = iperf3.Target(id="t", name="VPS", host="vps.example.com", port=5202)
    download = iperf3.arguments(target, reverse=True)
    assert download[:4] == ["-c", "vps.example.com", "-p", "5202"]
    assert "-R" in download and "--json-stream" in download
    assert download[download.index("-O") + 1] == str(iperf3.OMIT)
    upload = iperf3.arguments(target, reverse=False)
    assert "-R" not in upload
    # Die Probe beim Eintragen dauert eine Sekunde, da bliebe nach dem Anlauf nichts uebrig.
    assert "-O" not in iperf3.arguments(target, reverse=False, duration=iperf3.CHECK_SECONDS)


async def test_live_values_come_from_the_intervals(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_run(monkeypatch, FakeProcess(lines(START, INTERVAL, INTERVAL, END)))
    events: list[dict[str, object]] = []
    end = await iperf3._stream(["-c", "x"], "download", reporter(events), timeout=5)
    assert iperf3.received(end)[0] == pytest.approx(40.6)
    values = [event for event in events if event["type"] == "value"]
    assert values and values[0] == {"type": "value", "phase": "download", "mbps": 618.0}


async def test_an_error_line_ends_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_run(monkeypatch, FakeProcess(lines(START, REFUSED, {"event": "end", "data": {}}), returncode=1))
    with pytest.raises(MeasurementError) as caught:
        await iperf3._stream(["-c", "x"], "download", None, timeout=5)
    assert caught.value.code == "iperf3_failed"


async def test_output_without_a_result_is_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keine Fehlerzeile, aber auch kein Ergebnis: Das darf nicht als 0 Mbit/s durchgehen.
    fake_run(monkeypatch, FakeProcess(lines(START), returncode=1, stderr=b"iperf3: error - control socket has closed"))
    with pytest.raises(MeasurementError) as caught:
        await iperf3._stream(["-c", "x"], "upload", None, timeout=5)
    assert caught.value.code == "iperf3_failed"
    assert "control socket" in caught.value.detail


async def test_a_busy_server_is_tried_once_more(monkeypatch: pytest.MonkeyPatch) -> None:
    # Zwischen Download und Upload raeumt der Server noch auf. Ein zweiter Versuch reicht.
    attempts = []

    async def stream(_args: list[str], phase: str, _reporter: Reporter | None, _timeout: float) -> dict[str, Any]:
        attempts.append(phase)
        if len(attempts) == 1:
            raise MeasurementError("iperf3_busy", "the server is busy running a test")
        return END["data"]

    monkeypatch.setattr(iperf3, "_stream", stream)
    monkeypatch.setattr(asyncio, "sleep", _no_wait)
    target = iperf3.Target(id="t", name="VPS", host="vps.example.com", port=5201)
    end = await iperf3.run(target, reverse=False, phase="upload")
    assert len(attempts) == 2
    assert iperf3.received(end)[1] == 51_500_000


async def test_a_run_that_never_ends_is_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ein Port, der annimmt und dann schweigt, laesst iperf3 endlos warten. --connect-timeout hilft da nicht.
    process = fake_run(monkeypatch, FakeProcess([]))

    async def silence() -> bytes:
        await asyncio.sleep(10)
        return b""

    process.stdout.readline = silence  # type: ignore[method-assign]
    with pytest.raises(MeasurementError) as caught:
        await iperf3._stream(["-c", "x"], "download", None, timeout=0.6)
    assert caught.value.code == "iperf3_timeout"
    assert process.killed


async def _no_wait(_seconds: float) -> None:
    return None
