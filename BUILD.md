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

The exe is a ~45MB binary — never committed to the repo (see Notes below) — so it's
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
  server imports (`db.py`, `lookup.py`, `matching.py`, `ai_expansion.py`, `openfda.py`,
  `predicate_graph.py`) changes. The crawl-only modules (`crawl.py`, `pdf_extract.py`,
  `scope.py`) aren't part of this build and don't require a rebuild on their own.
- `pyinstaller.spec` is committed so the build configuration (entry point, hidden imports) is
  reproducible; `build/` and `dist/` (PyInstaller's own output folders) are gitignored — the
  compiled `.exe` itself isn't checked into the repo.
- The exe isn't code-signed, so Windows SmartScreen will likely flag it as an "unrecognized app"
  on first run for whoever downloads it — this is expected, not a build error.
