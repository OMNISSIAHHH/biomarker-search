# PyInstaller spec for BiomarkerSearchServer.exe — see BUILD.md for how to build with this.
#
# Packages only the day-to-day server (server/launcher.py -> server/main.py), not the periodic
# device+PDF crawl (indexer/crawl.py), which stays a source/Python step. The server's own
# dependency chain (fastapi, uvicorn, httpx, python-dotenv) is much lighter than the crawl's
# (which also needs pypdf/pymupdf/pytesseract/Pillow for OCR).
#
# Deliberately NOT collect_submodules("indexer") / ("server"): those are plain first-party
# packages with static imports, which PyInstaller's own Analysis already follows correctly from
# server/launcher.py (db/lookup/matching/ai_expansion/openfda/predicate_graph — server/main.py's
# real import chain, confirmed via indexer/lookup.py). Blanket-collecting the whole `indexer`
# package instead force-includes crawl-only modules the server never actually imports, notably
# indexer/pdf_extract.py — whose `import pymupdf` transitively pulls in pymupdf.table, which
# imports pandas (then scipy, then numpy), ballooning a ~15MB build into a ~100MB one for code
# that never runs in this exe. Confirmed by comparing build output with/without it.
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("fastapi")
    + collect_submodules("starlette")
)

a = Analysis(
    ["server/launcher.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="BiomarkerSearchServer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # keep the console window: it's the only running/status indicator a
                   # non-coder has that the server is alive, per launcher.py's print statements
    disable_windowed_traceback=False,
)
# Passing a.binaries/a.datas directly into EXE() (above), rather than routing them through a
# separate COLLECT(), is what makes this a single-file ("onefile") build — no onedir folder.
