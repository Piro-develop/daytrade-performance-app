"""Explicit static asset allow-list shared by both launchers."""
from pathlib import Path
ROOT = Path(__file__).resolve().parent
PUBLIC_FILES = {
    "index.html","app.js","styles.css","credit-styles.css",
    "judgment.mjs","judgment.css","judgment-config.json",
    "stocks.json","stock-readings.json","stock-search-aliases.json","manifest.webmanifest",
    "credit-calculation.mjs","position-allocation.mjs","spot-calculation.mjs",
    "tax-calculation.mjs","trade-editing.mjs","trade-deletion.mjs","summary-ui.mjs","profit-display.mjs",
}
def public_path(path):
    relative=path.lstrip("/") or "index.html"
    target=(ROOT/relative).resolve()
    if not target.is_relative_to(ROOT): return None
    if relative in PUBLIC_FILES: return target if target.is_file() else None
    for folder,suffix in (("assets/icons",".png"),("fonts",".woff2")):
        if relative.startswith(folder+"/") and target.is_relative_to(ROOT/folder) and target.suffix==suffix:
            return target if target.is_file() else None
    return None
