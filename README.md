# Biomarker Search _(biomarker-search)_

[![standard-readme compliant](https://img.shields.io/badge/readme%20style-standard-brightgreen.svg?style=flat-square)](https://github.com/OMNISSIAHHH/standard-readme)
[![license: Modified MIT](https://img.shields.io/badge/license-Modified%20MIT-blue.svg?style=flat-square)](LICENSE)

Search FDA 510(k) device clearances by biomarker, with visualization and Excel export

Type in a biomarker name (like "PSA" or "HbA1c") and see how many FDA-cleared lab tests already
exist for it — and, optionally, whether it's also offered as a lab-developed test in New York
State. Meant to help you quickly gauge whether a biomarker is a crowded space (lots of existing
tests) or an open opportunity (few or none).

Two parts: a browser interface (no install) and a local cross-check backend (a double-click
program, no coding needed — see [Install](#install)). **Run both — the backend is the default
workflow, not an optional add-on.** It finds real FDA approvals the browser alone structurally
cannot see (see [Background](#background)). The browser alone still works with zero setup —
useful for a fast first look, or if you'd rather skip the backend entirely — but treat that as
the reduced/fallback mode.

(A local checkout's folder name may differ from the repository name above, e.g.
`fda-510k-biomarker-search` — same project either way.)

> Unfamiliar word (like "510(k)" or "LDT")? Check the **[Glossary](#glossary)** below.

## Table of Contents

- [Security](#security)
- [Background](#background)
- [Install](#install)
  - [Dependencies](#dependencies)
- [Usage](#usage)
  - [Searching for a biomarker](#searching-for-a-biomarker)
  - [Reading your results](#reading-your-results)
  - [Sorting your results](#sorting-your-results)
  - [Filtering and narrowing your results](#filtering-and-narrowing-your-results)
  - [Exporting to Excel](#exporting-to-excel)
  - [Checking a specific device's paperwork ("Measurand")](#checking-a-specific-devices-paperwork-measurand)
  - [CLI](#cli)
- [Automatic abbreviation lookup (UMLS and AI crosscheck)](#automatic-abbreviation-lookup-umls-and-ai-crosscheck)
- [Searching lab-developed tests (LDT) in New York State](#searching-lab-developed-tests-ldt-in-new-york-state)
- [Things to keep in mind](#things-to-keep-in-mind)
- [Glossary](#glossary)
- [For developers](#for-developers)
- [API](#api)
- [Maintainers](#maintainers)
- [Thanks](#thanks)
- [Contributing](#contributing)
- [License](#license)

## Security

Everything you type and any browser Settings (Worker URLs, API keys) stay in your own browser —
nothing is sent anywhere except directly to the FDA and, if configured, New York's site, the FDA
paperwork site, NLM's UMLS database, Tavily, and your own local backend/AI model. Backend API
keys in `.env` stay on your machine — never uploaded or shared anywhere by this tool.

The packaged `BiomarkerSearchServer.exe` isn't digitally signed by a registered publisher (that
costs money, not worthwhile for a small free tool), so Windows SmartScreen will likely flag it as
an unrecognized app the first time you run it — expected, not a sign anything's wrong (see
[Install](#install)).

## Background

The backend does two things the browser alone structurally can't:

- **Reads bundled-panel reagents out of device PDFs.** Some devices measure a biomarker as part
  of a multi-antigen panel kit but never name it in FDA's searchable device data — only inside
  the device's own decision-summary PDF. The backend reads every device's cited "predicate" out
  of that PDF; if a device cites an already-confirmed match as its predicate, it's surfaced too,
  tagged **"inferred via predicate"** — shown separately, not counted in totals, since a cited
  predicate is a strong hint, not proof of an identical panel.
- **Precomputes the alternate-wordform check, so it's fast.** Same logic the browser runs live
  (see [Reading your results](#reading-your-results)), just computed once ahead of time instead
  of on every search — the browser alone has to make an extra network call per biomarker for
  this, which is noticeably slower.

510(k)-only, same as the browser search — no GUDID/UDI device-registration cross-check, no PMA
(Premarket Approval, a different FDA pathway for higher-risk Class III devices).

**Confirmed-match results work immediately for any biomarker, right after step 2 of**
[Install](#install) — nothing to wait on. The predicate-chain ("inferred via predicate") tier is
a bit different: it depends on `BiomarkerSearchServer.exe`'s companion `index.sqlite3` file
already having read the relevant device's paperwork. If your download included a pre-built
`index.sqlite3` next to the exe, this just works. If not (a fresh, empty `index.sqlite3` gets
created automatically the first time you search), predicate-chain results stay empty until the
crawl that builds this data has run at least once.

**Running that crawl no longer needs Python or a terminal** — with the local index server
running (step 2 of [Install](#install)), open **Settings** (gear icon) and click **Start
predicate crawl** near the bottom. Progress streams live in the **Platform activity** window at
the top of the page. Set real expectations before starting it: this reads every in-scope FDA
device's decision summary PDF (tens of thousands of documents) and can take **hours**, using real
network bandwidth and subject to openFDA's rate limits (1,000 requests/day without an API key,
120,000/day with one — see [Dependencies](#dependencies)). It only runs while the backend itself
is running; closing `BiomarkerSearchServer.exe` stops it. You can safely close the browser tab or
reload the page mid-crawl — reopening Settings picks the same crawl back up and replays its
progress so far, rather than losing it or starting over. A **Cancel** button appears while it's
running; cancelling keeps everything already fetched (at most the batch in progress, up to 50
devices, is lost).

Without the backend running (or if you skip it entirely), the tool still works from the browser
alone — a banner reading "Running in fallback mode" shows when this is the case — just without
predicate-chain results or the automatic abbreviation lookups below.

Related optional extras, each documented in its own section:

- **[Automatic abbreviation lookup](#automatic-abbreviation-lookup-umls-and-ai-crosscheck)** —
  resolve an unrecognized biomarker abbreviation to its full name, via UMLS and/or a
  search-grounded AI crosscheck.
- **["Check Measurand"](#checking-a-specific-devices-paperwork-measurand)** — confirm what a
  specific device actually measures by reading its official FDA paperwork.
- **[LDT search](#searching-lab-developed-tests-ldt-in-new-york-state)** — check New York
  State's lab-developed-test database for biomarkers with few or no FDA-cleared devices.

## Install

No coding, no installing Python, nothing typed into a black-and-white window required. Two files
work together: **`FDA510kBiomarkerSearch.html`** (the tool itself, opens in your normal browser)
and **`BiomarkerSearchServer.exe`** (a small helper program — see [Background](#background) for
what it adds and why it's worth the extra step).

1. Go to the **[Releases page](https://github.com/OMNISSIAHHH/biomarker-search/releases/latest)**
   and download the `.zip` under **Assets** (not the green **Code** button — that only gets you
   the source files, not the packaged program). Extract it (right-click → **Extract All** on
   Windows, double-click on Mac). *(Already have the folder? Skip this.)*
2. Double-click **`BiomarkerSearchServer.exe`**. A black window opens and, after a moment, prints
   a line ending in "Application startup complete" — that means it's running.
   **Leave this window open** while you use the tool; closing it just drops the tool back to
   browser-only mode (see [Background](#background)), it doesn't break anything.
   - Windows will very likely show a blue **"Windows protected your PC"** warning the first
     time — see [Security](#security). Click **More info**, then **Run anyway**. You'll only see
     this once.
3. Double-click **`FDA510kBiomarkerSearch.html`** — it opens in your browser.
4. Click the gear icon (⚙) → **Settings**, and paste `http://localhost:8000` into **Local index
   server URL**. This points the tool at the program you started in step 2.
5. Search — see [Usage](#usage).

### Dependencies

None of the above needs anything installed beyond the downloaded `.zip` itself. A few optional
features benefit from extra, manually-installed pieces:

- **API keys** (raises the openFDA rate limit, unlocks automatic abbreviation lookup — see
  [Automatic abbreviation lookup](#automatic-abbreviation-lookup-umls-and-ai-crosscheck) for
  which keys do what) — added via a `.env` text file, still no coding:
  1. In the same folder as `BiomarkerSearchServer.exe`, right-click an empty spot → **New** →
     **Text Document**.
  2. Rename the new file to exactly `.env` (delete the `.txt` at the end — Windows will warn
     about changing a file extension; confirm yes, that's intentional).
  3. Right-click it → **Open with** → **Notepad**, and add a line like:
     ```
     TAVILY_API_KEY=your-key-here
     ```
  4. Save and close Notepad, then close the black `BiomarkerSearchServer.exe` window (if it's
     still open) and double-click the exe again so it picks up the new setting.
- **[Ollama](https://ollama.com)**, installed locally with a small model pulled — required for the
  AI-crosscheck half of automatic abbreviation lookup specifically; everything else in this tool
  works without it. See [Automatic abbreviation lookup](#automatic-abbreviation-lookup-umls-and-ai-crosscheck).

## Usage

### Searching for a biomarker

1. Make sure the **FDA 510(k)** tab is selected (the default).
2. Type the biomarker name(s) you want — one per line or comma-separated:
   ```
   HbA1c
   Troponin
   PSA
   BNP
   ```
3. Click **Search**.

Type names the way they're normally written, including antibody names ("Anti-GAD65") or Greek
letters ("Anti-β2-GP1") — both are handled automatically.

**Platform activity window:** a dark, terminal-style panel at the top of the page shows exactly
what's happening in real time — which match tiers were tried, whether UMLS/an AI web crosscheck
were consulted and what they found, and (if you start one) predicate-crawl progress too. It's one
shared, continuously-scrolling log for whatever the tool is doing, not cleared between searches —
useful for seeing that a slow-feeling search (e.g. one triggering the AI crosscheck, which can
take 10-30 seconds) is actually working, not stuck.

### Reading your results

A bar chart and a table show the same results two ways.

**Table columns:**

| Column | Meaning |
|---|---|
| Rank | Position in the current sort order (see [Sorting your results](#sorting-your-results)) |
| Biomarker | The term you typed, with a tag if the tool had to search more loosely (see below) |
| Total Submissions | How many FDA filings mention this biomarker |
| Cleared (Approved) | How many were actually cleared. **Red** = 10 or more (crowded space); **green** = fewer than 10 |
| Unique Applicants | Distinct companies behind those submissions — lower than Total Submissions means a company filed more than once (see the [Submitted by filter](#filtering-and-narrowing-your-results)) |

Click a row to expand it: device name, submitting company, decision, approval date, an FDA
detail link, and a **Check Measurand** button ([below](#checking-a-specific-devices-paperwork-measurand)).

**Tags next to a biomarker name** (none mean the result is wrong — they signal match
confidence; an exact match is always most reliable):

- **Broad match** — no exact phrase match, so it searched ignoring word order
- **Antigen-only match** — same, and also ignoring the antibody class (IgG/IgA/IgM)
- **UMLS-resolved match** — nothing above matched, so the abbreviation's full name was looked up
  via UMLS (see [Automatic abbreviation lookup](#automatic-abbreviation-lookup-umls-and-ai-crosscheck))
- **AI-suggested match** — same, but UMLS didn't know it either, so the backend searched the web
  and had a local AI model extract the name from those results. More grounded than a cold guess,
  but still a generated extraction, not a database entry — worth a sanity check via
  **Check Measurand**
- **Fused-word match** — FDA sometimes writes "Anti" and the antigen as one fused word (e.g.
  "Anticardiolipin"); tried automatically for any antibody-style search
- **Alternate wordform match** — FDA device names aren't consistent about spacing/hyphens (e.g.
  "DS DNA" split apart vs. "dsDNA" fused); the tool automatically tries splitting fused words,
  swapping hyphens for spaces (and back), and fusing multi-word terms

### Sorting your results

- **Fewest approvals** (default) — least competition first, for spotting open opportunities.
- **Most recent approval** — most recently active first. Biomarkers with zero cleared devices
  have no date, so they sit at the bottom.

### Filtering and narrowing your results

All filters work together, update live (no re-search needed), and carry into the Excel export.

- **By date** — **From**/**To** month pickers bound which cleared devices count. **Clear** resets.
- **By company ("Submitted by")** — narrow every biomarker's device list to one company.
- **"Show only"** — type a biomarker or company name, click **Add**, to narrow the view to just
  matches (biomarker-name matches keep all its records; company matches narrow to that
  company's records only). Click a tag's **×** to remove it.
- **Rule out an FDA review panel** — short abbreviations can collide with unrelated fields (e.g.
  "RF" = *Rheumatoid Factor* or *Radio Frequency* ablation devices). Click **Rule out FDA review
  panel** to see every panel present in your results and manually exclude ones that clearly
  don't belong. Nothing is excluded automatically. **Clear all review panels** undoes this.

  **Which panels are safe to rule out, for a lab biomarker search specifically:** the panel names
  below are checked directly against FDA's own 510(k) data (not just general regulatory
  knowledge), so they match exactly what you'll see in the **Rule out FDA review panel** list.

  | Almost always safe to rule out | Where real biomarker tests actually live |
  |---|---|
  | General, Plastic Surgery; Orthopedic; Cardiovascular; Radiology; Dental; Ear, Nose, Throat; Ophthalmic; Anesthesiology; Physical Medicine; Gastroenterology, Urology; Obstetrics/Gynecology; General Hospital; Neurology | Immunology; Clinical Chemistry; Hematology; Microbiology; Pathology; Clinical Toxicology |

  The left column is hardware/surgical/imaging panels that never contain a lab assay — even
  blood-based biomarkers like troponin are classified under Clinical Chemistry, not
  Cardiovascular. The right column is exactly the scope the backend's predicate-chain crawl
  already bounds itself to (see `indexer/scope.py`), for the same reason: a genuine lab test
  realistically only ever lands in one of those six. Treat this as a strong default, not a
  guarantee — for an unfamiliar biomarker, it's still worth a glance at what's actually in a
  ruled-out panel's results before trusting the exclusion blindly.

  Two panels don't fit cleanly into either column, worth knowing about rather than ruling out or
  in by default: **Medical Genetics** (a tiny panel — 17 devices FDA-wide — for genetic-test
  submissions; plausible for a gene-based biomarker but untested by this tool so far, so treat it
  as a judgment call) and **Unknown** (devices with no panel assigned at all — a real, sizeable
  bucket; don't assume ruling it out is safe just because its name suggests nothing's there).
- **Clear all filters** — resets date range, company filter, show-only list, and ruled-out
  panels together.

### Exporting to Excel

**Export to Excel** downloads a color-formatted spreadsheet matching whatever's currently on
screen (sort order + active filters) — bold colored headers, and the same red/green
crowded-vs-open shading from the on-screen table carried into the **Cleared (Approved)** column,
so the file reads the same way away from the browser. Sheets:

- **Search Info** — when/what/how this export was produced, so the file explains itself later.
- **Summary** — one row per biomarker, totals + Unique Applicants.
- **Biomarker Applicants** — one row per biomarker with its total submissions, unique-company
  count, and the actual company list.
- **Details** — one row per confirmed device, across every biomarker searched.
- **Unconfirmed Matches** — every unconfirmed candidate (from the backend's predicate-chain
  crawl), labeled by Match Type, kept separate so it's never mistaken for a confirmed result.

Running the LDT cross-check adds two more sheets, plus its own **Export to Excel** button.

### Checking a specific device's paperwork ("Measurand")

Every device row has a **Check Measurand** button: downloads the device's Decision Summary PDF
and checks the specific line stating what it actually measures — more authoritative than the
device name alone. Shows **Matches** or **No match**.

Most documents label this "Measurand" or "Analyte"; multi-parameter devices (e.g. hematology
analyzers) have neither, so the tool falls back to "Type of Test" or "Intended Use" instead.
For an older or poorly-scanned document with no real text layer at all, it automatically falls
back to OCR (in your browser, no setup) instead of giving up — slower for those specific
documents, but no different to use otherwise. A result found this way is labeled **via OCR**,
since OCR occasionally misreads a character worth a second look.

**Already works out of the box:** FDA's site blocks direct browser access to this PDF, so this
needs a small Cloudflare "Worker" go-between — a shared one is already pre-filled in Settings,
no setup needed to try it. That shared instance has a daily limit and no uptime guarantee,
though, so if you're using this regularly, deploy your own (**[worker/README.md](worker/README.md)**,
~5 minutes, no coding) and paste its URL into Settings to replace the shared one.

### CLI

The browser tool and packaged exe cover day-to-day use with no command line at all. A CLI exists
for the backend's device+PDF crawl, useful for scripted/unattended runs (e.g. a scheduled
re-crawl) — see [For developers](#for-developers) for the full setup:

```bash
python -m indexer.crawl
```

## Automatic abbreviation lookup (UMLS and AI crosscheck)

There's no built-in abbreviation list — every term's full medical name is resolved
automatically, via UMLS first, then a search-grounded AI crosscheck for whatever UMLS doesn't
cover. Both optional; without either, the tool still finds whatever the exact/broad/antigen-only
tiers can on their own, just without an alternate name to fall back on.

**UMLS** — go to **[uts.nlm.nih.gov/uts/license](https://uts.nlm.nih.gov/uts/license)**, sign in
(Login.gov works), agree to the license terms. This is a real license request reviewed by hand
by the National Library of Medicine — **up to 3 business days** before approval. Once approved,
generate an API key from your profile. Paste it into **Settings** → **UMLS API key** (browser
tool) or `UMLS_API_KEY` in `.env` (backend) — no separate Worker needed. Flagged
**UMLS-resolved match**, unverified since nobody's manually confirmed the lookup — a quick
sanity check via **Check Measurand** is worthwhile.

**Search-grounded AI crosscheck (backend only)** — for whatever UMLS doesn't cover, including
the wait while a UMLS license is pending. It searches the web for the term first (via
[Tavily](https://tavily.com), free tier: 1,000 searches/month, no card, instant signup), then
has a local Ollama model extract the full name **from those actual search results** — not from
its own memorized recall. A grounding check then confirms the model's answer actually traces
back to the retrieved text before trusting it, rather than accepting whatever it says.

Setup, via `.env` (see [Dependencies](#dependencies) or [For developers](#for-developers)):
`TAVILY_API_KEY` from
[tavily.com](https://tavily.com), plus a local [Ollama](https://ollama.com) install with a small
model pulled (`ollama pull llama3.2:3b`) and set as `LOCAL_LLM_MODEL`. Use a small,
**non-reasoning** model — avoid Qwen3, DeepSeek-R1, QwQ, and similar "thinking" models here,
since they default to a long internal chain-of-thought before answering (confirmed to take over
20 seconds just to decide how to say "hello") with no benefit for this task. Flagged
**AI-suggested match** — more grounded than a cold guess, but still a generated extraction, not
a database entry, so it's kept more cautious than a UMLS-resolved match and worth a sanity check
via **Check Measurand**.

## Searching lab-developed tests (LDT) in New York State

A biomarker with 0 FDA-cleared devices doesn't necessarily mean nobody tests for it — it might
be an LDT (a test a lab builds and runs in-house; see the [Glossary](#glossary)). New York State
keeps a public list, searchable here too, by term match only (no AI expansion on this side — an
AI-resolved synonym's phrasing turned out to cause more false matches than it prevented against
New York's simpler "any word" search).

**Directly:** click the **LDT** tab and search the same way.

**Automatically after an FDA search:** if any biomarker showed **2 or fewer** FDA-cleared
devices, a button appears offering to check all of them against New York's list in one pass — a
low-but-nonzero count can still point to a real LDT-only opportunity, not just a strict zero.

**Already works out of the box** — same reason and same shared-instance caveats as Measurand
above.

### If nothing turns up

New York's list only covers labs holding a New York permit — a small slice of all labs
nationally. "No matching LDTs found" doesn't mean nobody offers it. A **Search Google for
"&lt;name&gt; LDT"** link then appears, which often surfaces the actual offering lab (ARUP, Mayo
Clinic Laboratories, LabCorp, etc.).

## Things to keep in mind

- **"Cleared"** always means the FDA's "Substantially Equivalent" decision.
- Results are capped at 300 devices per biomarker. The total count shown is still accurate past
  that; only the first 300 are listed/exported.
- Research purposes only — not medical advice, never for patient-care decisions. Double-check
  anything important on [FDA's own site](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfPMN/pmn.cfm).
- A search result is cached the first time a term is looked up, so a repeat search reads
  instantly from the local index rather than re-querying openFDA/UMLS/the AI crosscheck. Check
  **Force refresh (ignore cached results)** next to the Search button to re-resolve a term from
  scratch instead — worth doing after a tool update, or if an earlier AI/UMLS answer looked
  wrong. Deleting `index.sqlite3` next to the exe clears everything at once (also clears the
  predicate crawl, so it'll need re-running).

## Glossary

| Term | Plain-English meaning |
|---|---|
| **Biomarker** | A measurable substance in the body (a protein, antibody, hormone, etc.) used to test for a disease or condition. |
| **FDA 510(k)** | A pathway the FDA uses to clear most lab tests and medical devices for sale, by showing a new device is "substantially equivalent" to one already on the market. Each cleared device gets a reference number starting with **K** (e.g. `K123456`). |
| **De Novo (DEN)** | A different FDA pathway, used for genuinely novel devices that have nothing existing to compare against. These get a reference number starting with **DEN** instead of K. This tool treats them the same as 510(k) devices in its results. |
| **Cleared / Approved** | The FDA decided the device is "Substantially Equivalent" and it can be legally sold. |
| **LDT (Lab-Developed Test)** | A test that a single laboratory designs, builds, and runs in-house, rather than buying a ready-made FDA-cleared kit. These are regulated differently than FDA-cleared devices — some states, like New York, require their own separate approval for them. |
| **Decision Summary** | The FDA's official write-up explaining why a specific device was cleared — usually a PDF, a few pages long, with a standard structure. |
| **FDA review panel (advisory committee)** | The medical specialty group inside the FDA that reviewed a given device — e.g. Immunology, Clinical Chemistry, General Surgery. Every cleared device is routed to one; genuine lab tests almost always land in a handful of diagnostic-related panels, never a surgical/hardware one. |
| **Measurand** | The technical term (used in that FDA paperwork) for exactly what a test measures — e.g. "Anti-GAD65 antibodies in human serum." |
| **Worker** | A small, free program that runs on Cloudflare's servers (not your computer) and acts as a go-between, letting this tool reach a website that would otherwise block it directly. You set one up once by copy-pasting code into a web page — no programming needed. See [worker/README.md](worker/README.md). |
| **API / API key** | A way for one computer program to ask another for data automatically (in this case, this tool asking the FDA's database for results). An "API key" is just a free password that raises how many searches per day you're allowed — you don't need one to use this tool, it just helps if you're doing a lot of searching. |
| **openFDA** | The FDA's own public, free database that this tool queries. |
| **UMLS (Unified Medical Language System)** | A huge, free medical terminology database run by the National Library of Medicine (NLM) that combines many other medical vocabularies and knows an enormous number of abbreviations and their full names. This tool can optionally use it to resolve a biomarker abbreviation it doesn't already recognize. |

## For developers

Plain HTML/CSS/JS on the frontend, no build tooling — [Chart.js](https://www.chartjs.org/) and
[xlsx-js-style](https://github.com/gitbrent/xlsx-js-style) load from a CDN (see
[Thanks](#thanks)). The cross-check backend (`indexer/` + `server/`) is a separate Python
project, packaged for end users as `BiomarkerSearchServer.exe` via PyInstaller (see
[BUILD.md](BUILD.md)) or run from source below; both load config from a `.env` file via
`python-dotenv`. See [worker/README.md](worker/README.md) for the two optional Cloudflare Worker
proxies — UMLS needs no proxy, its API sends CORS headers allowing direct browser calls.

Everything below assumes running the backend from source instead of the packaged exe — needed if
you're modifying the code or rebuilding the exe (see [BUILD.md](BUILD.md)). The device+PDF crawl
that fills in predicate-chain results can now be started from the UI itself (Settings → **Start
predicate crawl**, see [Background](#background)) — the CLI version below still exists and still
works identically, useful for scripted/unattended runs (e.g. a scheduled re-crawl) rather than as
the only way to do it.

**Running the server from source**, in place of the exe:
```bash
pip install -r indexer/requirements.txt
pip install -r server/requirements.txt
uvicorn server.main:app --reload
```
Reads `.env` and creates/reads `index.sqlite3` in the repo root either way — same as the exe,
just relative to the repo instead of wherever the exe sits.

**The device+PDF crawl (CLI)** — builds/refreshes the corpus the predicate-chain tier depends on:
```bash
python -m indexer.crawl
```
Confirmed matches already work without this; it only unlocks the "inferred via predicate" tier.
Takes a while the first run (reading real PDFs, politely rate-limited); re-run periodically to
pick up newly-cleared devices (skips PDFs already fetched, so a re-run is fast). If you're
distributing a ZIP to non-coder users, you can run this once yourself and include the resulting
`index.sqlite3` next to the exe in that ZIP so predicate-chain results work for them immediately
— or just let them trigger it themselves from Settings, since the exe can now do this on its own.

**API keys — `.env` at the repo root** (same file the exe reads, just via a text editor instead
of the New-Text-Document trick in [Dependencies](#dependencies)):
```
OPENFDA_API_KEY=      # raises the openFDA rate limit from 1,000/day to 120,000/day
UMLS_API_KEY=         # automatic abbreviation lookup — see below
TAVILY_API_KEY=       # automatic abbreviation lookup fallback — see below
LOCAL_LLM_URL=http://localhost:11434
LOCAL_LLM_MODEL=llama3.2:3b
```
All optional — the tool works with none of them set, just with fewer automatic lookups and a
lower openFDA rate limit. `python -m indexer.crawl --api-key KEY` also works instead of `.env`.

**Optional: OCR for scanned decision summaries.** Some older 510(k) submissions are scanned
paper documents with no text layer — nothing to parse a Measurand or predicate table out of.
Install the free [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) OCR engine and the
crawl automatically falls back to it for exactly those documents (documents with a normal text
layer are unaffected, so this adds no time for the majority of devices):
- **Windows**: run the installer from the
  [UB-Mannheim Tesseract page](https://github.com/UB-Mannheim/tesseract/wiki), then add its
  install folder (containing `tesseract.exe`, usually `C:\Program Files\Tesseract-OCR`) to your
  `PATH`.
- **Mac**: `brew install tesseract`
- **Linux**: `sudo apt install tesseract-ocr`

Without Tesseract, the crawl behaves exactly as before this feature existed.

**This OCR fallback is source-only** — the packaged exe's Settings-triggered crawl does not
include it (keeping the exe's download size small), so a scanned, image-only decision-summary PDF
is simply skipped by the UI-triggered crawl, exactly as it would be with Tesseract not installed.
If you need OCR coverage, run `python -m indexer.crawl` from source instead, with Tesseract
installed per above.

**Building `BiomarkerSearchServer.exe`** — see [BUILD.md](BUILD.md).

## API

The local backend (`BiomarkerSearchServer.exe`, or `uvicorn server.main:app` from source — see
[For developers](#for-developers)) exposes a small HTTP API on `http://localhost:8000` by
default. The browser tool is the intended client, but every endpoint is plain JSON/SSE over
HTTP and works fine from `curl` or a browser address bar too — e.g. to force a fresh lookup for
one term past its cache (see [Things to keep in mind](#things-to-keep-in-mind)):
`http://localhost:8000/biomarker/mir-31?refresh=true`.

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Liveness check; also reports the `index.sqlite3` path in use. |
| `/biomarker/{term}` | GET | The full tiered match pipeline for one term — confirmed matches, predicate-inferred matches, and the resolved expansion. Cached after first run; `?refresh=true` bypasses the cache. |
| `/biomarker/{term}/stream` | GET | Same as above, but as Server-Sent Events — each match-tier/expansion stage streams the instant it happens, rather than only once the whole pipeline finishes. |
| `/expansion/{term}` | GET | Just the resolved full-name/synonym expansion (UMLS or AI crosscheck), without running the FDA match tiers. `?refresh=true` bypasses the cache. |
| `/crawl/start` | POST | Starts the device+PDF crawl in the background (optional `committees`, `api_key`). 409s if one is already running. |
| `/crawl/stream` | GET | Server-Sent Events of crawl progress; replays everything so far on connect, then streams live. |
| `/crawl/cancel` | POST | Cancels the running crawl. Already-committed batches (up to 50 devices at a time) are kept. |
| `/crawl/status` | GET | A cheap, non-streaming snapshot: current status plus real row counts from the index. |

## Maintainers

[@OMNISSIAHHH](https://github.com/OMNISSIAHHH)

## Thanks

- [Chart.js](https://www.chartjs.org/) — the results bar chart.
- [xlsx-js-style](https://github.com/gitbrent/xlsx-js-style) — a style-capable
  [SheetJS](https://sheetjs.com/) Community Edition fork (same `XLSX` API, adds the cell
  colors/fonts used in the Excel export).
- [Tesseract.js](https://tesseract.projectnaptha.com/) — in-browser OCR fallback for Check
  Measurand on scanned/image-only Decision Summaries.
- [openFDA](https://open.fda.gov/) — the FDA's own public device-clearance data this tool queries.
- The National Library of Medicine's [UMLS](https://www.nlm.nih.gov/research/umls/index.html) —
  the medical-abbreviation lookup.
- [Tavily](https://tavily.com) and [Ollama](https://ollama.com) — the search-grounded AI
  crosscheck for abbreviations UMLS doesn't cover.
- [Cloudflare Workers](https://workers.cloudflare.com/) — the small proxies that let the browser
  tool reach FDA-paperwork PDFs and New York's LDT list directly (see
  [worker/README.md](worker/README.md)).

## Contributing

Questions, bug reports, and feature requests are welcome via
[GitHub Issues](https://github.com/OMNISSIAHHH/biomarker-search/issues). PRs are welcome too — for
anything beyond a small fix, opening an issue first to discuss the approach is appreciated. See
[For developers](#for-developers) and [BUILD.md](BUILD.md) for how to run this from source and
rebuild the packaged exe.

## License

`SEE LICENSE IN` [LICENSE](LICENSE) — a modified MIT license, © 2026 Francis Liu. Free to use,
modify, and share, including internally at a company. The one thing it doesn't allow is selling
the software itself or bundling it into something sold, without the copyright holder's
permission.
