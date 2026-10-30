"""Browser-directed scenes from the official Lightning Agent page.

The page is the single visual source.  Controls are selected by their stable,
user-facing identifiers rather than by coordinates, so every scene records the
same layer a visitor would see in /app/.
"""

from __future__ import annotations

import os
from pathlib import Path


SCENES = (
    ("america-do-sul", None, "Panorama — América do Sul"),
    ("satelite", "#clouds-toggle", "Satélite IR — nuvens convectivas"),
    ("radar", '[data-view="radar"]', "Radar — chuva observada"),
    ("raios", '#observed-toggle', "Raios observados"),
    ("severidade", '[data-view="severidade"]', "Severidade — chuva e raios"),
    ("previsao-ecens", '[data-view="deterministico"]', "Previsão de raios — ECENS"),
    ("inundacoes", '[data-view="inundacoes"]', "Potencial de inundação"),
)


def capturar_cenas(app_url: str, directory: Path) -> list[Path]:
    """Click official map controls and capture a continental-to-Brazil sequence."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright não configurado no worker") from exc

    directory.mkdir(parents=True, exist_ok=True)
    browser_path = os.environ.get("CHROMIUM_BIN", "") or None
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=browser_path,
            args=["--no-sandbox", "--disable-gpu"],
        )
        page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        page.goto(app_url, wait_until="networkidle", timeout=60_000)
        page.locator("#map").wait_for(state="visible", timeout=30_000)
        page.wait_for_timeout(5_000)
        captures: list[Path] = []
        for index, (name, selector, _title) in enumerate(SCENES):
            if selector:
                page.locator(selector).click(timeout=20_000)
                page.wait_for_timeout(4_000)
            if name == "previsao-ecens":
                page.locator('[data-fonte="ecens"]').click(timeout=20_000)
                page.wait_for_timeout(4_000)
            # The initial continental overview stays untouched.  The remaining
            # scenes zoom from the Brazilian centre of the visible South America.
            if index == 1:
                box = page.locator("#map").bounding_box()
                if box:
                    page.mouse.move(box["x"] + box["width"] * .56, box["y"] + box["height"] * .57)
                    page.mouse.wheel(0, -1_600)
                    page.wait_for_timeout(2_000)
            destination = directory / f"{index:02d}-{name}.png"
            # Hide interface controls only during capture. Keep the legend and
            # provider attribution visible, and restore controls for the next click.
            page.evaluate("""title => {
                const label = document.createElement('div');
                label.id = 'broadcast-caption';
                label.textContent = title + ' | ' +
                    (document.querySelector('#period')?.textContent || 'Consulte a legenda');
                label.style.cssText = 'position:absolute;top:12px;left:12px;z-index:1000;'
                    + 'background:#091422;color:white;padding:12px 18px;font:24px sans-serif;'
                    + 'max-width:90%;border-radius:6px';
                document.querySelector('.stage').appendChild(label);
            }""", _title)
            style = page.add_style_tag(content="""
                .topbar, .map-rail, .chat, .map-hint,
                .leaflet-control-zoom { visibility: hidden !important; }
                .stage { --chat-h: 0px !important; }
                .legend { font-size: 20px !important; max-width: 340px !important;
                          bottom: 36px !important; }
                .legend-title, .legend-note, .legend-msg, .legend-scale,
                .legend-valid { font-size: 17px !important; }
                .leaflet-bottom { bottom: 0 !important; }
            """)
            page.locator(".stage").screenshot(path=str(destination))
            style.evaluate("element => element.remove()")
            page.locator('#broadcast-caption').evaluate("element => element.remove()")
            captures.append(destination)
        browser.close()
    return captures
