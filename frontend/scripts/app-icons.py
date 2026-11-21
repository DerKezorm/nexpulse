"""The icons for the home screen, rendered once from the light version of the mark.

    python frontend/scripts/app-icons.py

Same shape as components/Logo.tsx and public/logo.svg; the source of every version is nexapps/icons-vergleich/neu.py.
Rendered with Playwright for Python (Chromium without a window).

The maskable icon is cropped by Android, so the mark sits smaller on a full white square. The Apple touch icon is full
bleed and without transparency: iOS rounds it itself.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

PUBLIC = Path(__file__).resolve().parent.parent / "public"

VERLAUF = """<defs><linearGradient id="g" gradientUnits="userSpaceOnUse" x1="10" y1="10" x2="54" y2="54">
  <stop offset="0" stop-color="#bef264"/><stop offset=".5" stop-color="#65a30d"/><stop offset="1" stop-color="#365314"/>
</linearGradient></defs>"""
ZEICHEN = """<g transform="translate(0 -3)"><path d="M14.4 47.5A19 19 0 1 1 49.6 47.5" fill="none" stroke="url(#g)"
  stroke-opacity=".3" stroke-width="4.6" stroke-linecap="round"/><path d="M14.4 47.5A19 19 0 0 1 45.4 26.6" fill="none"
  stroke="url(#g)" stroke-width="4.6" stroke-linecap="round"/><path d="M32 40 42 28.5" stroke="#4d8f0a" stroke-width="3.8"
  stroke-linecap="round"/><circle cx="32" cy="40" r="4.6" fill="#4d8f0a" stroke="#fff" stroke-width="2"/></g>"""


def kachel(s: int) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="{s}" height="{s}">{VERLAUF}'
            '<rect x="2" y="2" width="60" height="60" rx="16" fill="#fff"/>'
            '<rect x="2.75" y="2.75" width="58.5" height="58.5" rx="15.3" fill="none" stroke="#65a30d" stroke-opacity=".35" '
            f'stroke-width="1.5"/>{ZEICHEN}</svg>')


def voll(s: int, m: float) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="{s}" height="{s}">{VERLAUF}'
            f'<rect width="64" height="64" fill="#fff"/><g transform="translate(32 32) scale({m}) translate(-32 -31)">{ZEICHEN}</g></svg>')


def randlos(s: int) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="2 2 60 60" width="{s}" height="{s}">{VERLAUF}'
            f'<rect x="2" y="2" width="60" height="60" fill="#fff"/>{ZEICHEN}</svg>')


BILDER = [
    ("icon-192.png", kachel(192), 192, False),
    ("icon-512.png", kachel(512), 512, False),
    ("icon-maskable-512.png", voll(512, 0.82), 512, True),
    ("apple-touch-icon.png", randlos(180), 180, True),
]


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, svg, size, opaque in BILDER:
            page = browser.new_page(viewport={"width": size, "height": size})
            page.set_content(f'<body style="margin:0;background:transparent">{svg}</body>')
            bild = Image.open(io.BytesIO(page.locator("svg").screenshot(omit_background=True)))
            page.close()
            assert bild.size == (size, size), (name, bild.size)
            (bild.convert("RGB") if opaque else bild.convert("RGBA")).save(PUBLIC / name, optimize=True)
            print("written:", PUBLIC / name)
        browser.close()


if __name__ == "__main__":
    main()
