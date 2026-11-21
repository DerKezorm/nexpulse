"""Das gebaute Frontend hinter FastAPI: Zeichen, Symbole und Manifest."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import _mount_frontend

INDEX = '<div id="root"></div>'
PUBLIC = Path(__file__).resolve().parents[2] / "frontend" / "public"


def png(path: Path) -> tuple[int, int, int]:
    """Breite, Hoehe und Farbtyp aus dem Kopf einer PNG (2 = RGB ohne Transparenz, 6 = mit)."""
    head = path.read_bytes()[:26]
    assert head[1:4] == b"PNG", path
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big"), head[25]


def _served(tmp_path: Path) -> tuple[TestClient, list[str]]:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX, encoding="utf-8")
    (dist / "assets" / "app-1a2b3c.js").write_text("console.log(1)", encoding="utf-8")
    files = [p.relative_to(PUBLIC).as_posix() for p in PUBLIC.rglob("*") if p.is_file()]
    for name in files:
        (dist / name).parent.mkdir(parents=True, exist_ok=True)
        (dist / name).write_bytes((PUBLIC / name).read_bytes())
    site = FastAPI()
    _mount_frontend(site, dist)
    return TestClient(site), files


def test_every_file_of_public_is_asked_for_again_but_hashed_files_are_not(tmp_path: Path) -> None:
    # 21.11.2026: Dateien ohne Pruefsumme im Namen behielt der Browser nach einem Update, so blieb das alte Zeichen.
    client, files = _served(tmp_path)
    assert "logo.svg" in files and "manifest.webmanifest" in files
    for name in files:
        answer = client.get("/" + name)
        assert answer.status_code == 200 and answer.headers.get("cache-control") == "no-cache", name
    assert "no-cache" not in client.get("/assets/app-1a2b3c.js").headers.get("cache-control", "")


def test_the_manifest_goes_out_with_its_type(tmp_path: Path) -> None:
    client, _ = _served(tmp_path)
    answer = client.get("/manifest.webmanifest")
    assert answer.headers["content-type"].startswith("application/manifest+json")
    assert answer.json()["name"] == "nexpulse"


def test_nexpulse_installs_as_an_app() -> None:
    manifest = json.loads((PUBLIC / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert (manifest["name"], manifest["start_url"], manifest["display"]) == ("nexpulse", "/", "standalone")
    sizes = {(i["sizes"], i["purpose"]): i["src"] for i in manifest["icons"]}
    assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= set(sizes)
    for (size, purpose), src in sizes.items():
        assert src.endswith("?v=2"), src
        if size != "any":
            width, height, colour = png(PUBLIC / src.lstrip("/").split("?")[0])
            assert f"{width}x{height}" == size, src
            if purpose == "maskable":  # Android schneidet zu: bis an den Rand gefuellt, nichts durchsichtig
                assert colour == 2, src
    assert png(PUBLIC / "apple-touch-icon.png") == (180, 180, 2)


def test_the_mark_follows_the_system_and_its_addresses_carry_a_version() -> None:
    mark = (PUBLIC / "logo.svg").read_text(encoding="utf-8")
    assert "@media (prefers-color-scheme: dark)" in mark and "#0d110a" in mark
    page = (PUBLIC.parent / "index.html").read_text(encoding="utf-8")
    for part in ('href="/logo.svg?v=2"', '<link rel="manifest" href="/manifest.webmanifest" />',
                 '<link rel="apple-touch-icon" href="/apple-touch-icon.png?v=2" />'):
        assert part in page, part
