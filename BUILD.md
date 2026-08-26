# Building BiomarkerSearchServer.exe

This is only needed if you're modifying the backend code and need to rebuild the exe that gets
handed out to non-coder users. If you just want to run the server day-to-day, see the README's
"Getting started" section instead — you don't need any of this.

## One-time setup

From the repo root, with Python installed:

```bash
pip install -r server/requirements.txt
pip install pyinstaller
```

## Build

```bash
pyinstaller pyinstaller.spec
```

The finished executable is written to `dist/BiomarkerSearchServer.exe`. It creates
`index.sqlite3` and reads an optional `.env` from whatever folder it's actually run from, not
from the repo.

## Publishing a new release

The exe is a ~40MB binary — never committed to the repo (see Notes below) — so it's
distributed via **GitHub Releases** instead, as a single downloadable `.zip`. The README's
"Getting started" links to the latest release, not the repo's own "Download ZIP" (which only
contains source files, no compiled exe).

```bash
mkdir -p dist/bundle
cp dist/BiomarkerSearchServer.exe FDA510kBiomarkerSearch.html README.md dist/bundle/
cd dist/bundle && zip -r ../biomarker-search-vX.Y.Z.zip . && cd ../..
gh release create vX.Y.Z dist/biomarker-search-vX.Y.Z.zip --title "vX.Y.Z — Biomarker Search" --notes "..."
```

Bump `vX.Y.Z` each time (e.g. `v1.0.1`) — GitHub Releases won't let you reuse a tag. Before
zipping, do a real smoke test of that exact exe (start it, hit `/health`, run a real search)
so a broken build never gets published for someone to download.

## Notes

- Rebuild whenever `server/main.py`, `server/launcher.py`, or anything under `indexer/` that the
  server imports changes — that's now `db.py`, `lookup.py`, `matching.py`, `ai_expansion.py`,
  `openfda.py`, `predicate_graph.py`, `trace.py`, **and `crawl.py`/`pdf_extract.py`/`scope.py`**
  (the predicate crawl is triggerable from the UI now — see `server/main.py`'s `/crawl/*`
  endpoints — so those three modules are part of this build's closure too, not "crawl-only,
  no rebuild needed" anymore).
- `pyinstaller.spec` explicitly excludes `pymupdf`/`fitz`/`pytesseract`/`PIL` even though
  `indexer/pdf_extract.py` (now bundled) references them — those are only used by its OCR
  fallback, imported lazily inside function bodies. PyInstaller's Analysis still detects lazy
  imports and would bundle them (and their heavy transitive pandas/scipy/numpy chain) without
  the exclude list. This means the **packaged exe's crawl does not OCR scanned PDFs** — see
  README's OCR section. Confirm the exe still lands close to ~40MB after any spec change; a
  jump toward ~100MB+ means one of these leaked back in.
- `pyinstaller.spec` is committed so the build configuration (entry point, hidden imports,
  excludes) is reproducible; `build/` and `dist/` (PyInstaller's own output folders) are
  gitignored — the compiled `.exe` itself isn't checked into the repo.
- `server/requirements.txt` includes `httpx` and `pypdf` (needed by `server/main.py` directly and
  by the now-bundled `indexer/crawl.py`/`pdf_extract.py`) — keep OCR's extras
  (`pymupdf`/`pytesseract`/`Pillow`) out of it; those stay in `indexer/requirements.txt` only,
  for from-source use.
- The exe isn't code-signed, so Windows SmartScreen will likely flag it as an "unrecognized app"
  on first run for whoever downloads it — this is expected, not a build error.
