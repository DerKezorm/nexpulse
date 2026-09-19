"""Jeder Testlauf bekommt ein eigenes, leeres Datenverzeichnis."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

_DATA = tempfile.mkdtemp(prefix="nexpulse-tests-")
os.environ["NEXPULSE_DATA_DIR"] = _DATA
os.environ["NEXPULSE_DISABLE_BACKGROUND"] = "1"
os.environ["NEXPULSE_BCRYPT_ROUNDS"] = "4"
os.environ["NEXPULSE_FRONTEND_DIST"] = os.path.join(_DATA, "no-frontend")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import ApiKey, Result, Schedule, Setting  # noqa: E402
from app.services.engines import registry  # noqa: E402
from app.services.engines.base import Measurement, MeasurementError, Reporter, ServerInfo  # noqa: E402
from app.services.runner import runner  # noqa: E402

UI = {"X-Requested-By": "nexpulse"}


@pytest.fixture(autouse=True)
def clean_db() -> Iterator[None]:
    init_db()
    with SessionLocal() as db:
        for model in (Result, Schedule, ApiKey, Setting):
            db.execute(delete(model))
        db.commit()
    runner.live = None
    runner._task = None
    yield


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


class FakeEngine:
    """Misst nichts, liefert feste Werte oder einen Fehler."""

    name = "fake"

    def __init__(self, down: float = 900.0, up: float = 45.0, ping: float = 12.0, fail: str = "") -> None:
        self.down, self.up, self.ping, self.fail = down, up, ping, fail
        self.calls: list[str | None] = []

    async def servers(self) -> list[ServerInfo]:
        return [ServerInfo(id="s1", name="Fake server", location="Nowhere")]

    async def measure(self, server_id: str | None, reporter: Reporter) -> Measurement:
        self.calls.append(server_id)
        reporter.phase("ping")
        reporter.ping(self.ping)
        if self.fail:
            raise MeasurementError(self.fail, "fake failure")
        reporter.phase("download")
        reporter.value("download", self.down, force=True)
        reporter.phase("upload")
        reporter.value("upload", self.up, force=True)
        return Measurement(
            download_mbps=self.down,
            upload_mbps=self.up,
            ping_ms=self.ping,
            jitter_ms=1.5,
            server=ServerInfo(id=server_id or "s1", name="Fake server", location="Nowhere"),
            isp="Example ISP",
        )


@pytest.fixture
def fake_engine() -> Iterator[FakeEngine]:
    engine = FakeEngine()
    previous = registry.replace("cloudflare", engine)
    yield engine
    registry.replace("cloudflare", previous)
