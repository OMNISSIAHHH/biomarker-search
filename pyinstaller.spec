# PyInstaller spec for BiomarkerSearchServer.exe — see BUILD.md for how to build with this.
#
# Packages the day-to-day server (server/launcher.py -> server/main.py) AND the device+PDF
# predicate crawl (indexer/crawl.py) it can now trigger via /crawl/start — the exe is the single
# distribution artifact, there's no separate crawl-only binary.
#
# Deliberately NOT collect_submodules("indexer") / ("server"): those are plain first-party
# packages with static imports, which PyInstaller's own Analysis already follows correctly from
# server/launcher.py's real import chain — server/main.py now does `from indexer import crawl`,
# which is what pulls indexer.crawl (and transitively indexer.pdf_extract, indexer.scope) in,
# the same static-analysis way db/lookup/matching/ai_expansion/openfda/predicate_graph already
# were. No blanket indexer collection needed or wanted.
#
# indexer/pdf_extract.py's OCR fallback lazily imports pymupdf/pytesseract/PIL inside function
# bodies (not at module top-level) — PyInstaller's bytecode-scanning Analysis still finds these
# and would bundle them anyway, and pymupdf's own pymupdf.table submodule transitively pulls in
# pandas -> scipy -> numpy, ballooning a ~45MB build into a ~100MB+ one for OCR code most PDFs
# never need (confirmed earlier by comparing build output with/without it). Excluded below —
# pdf_extract.py's own `except Exception: return False` in _ocr_available() then degrades this
# to "OCR unavailable" at runtime, identical to "Tesseract not installed" today. This means the
# UI-triggered crawl in the packaged exe does NOT OCR scanned (image-only) decision-summary
# PDFs — that stays a from-source-only capability (see BUILD.md / README's OCR section).
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
    excludes=["pymupdf", "fitz", "pytesseract", "PIL"],
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
