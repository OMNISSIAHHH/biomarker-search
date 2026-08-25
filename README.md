# Biomarker Search

**What this is:** type in a biomarker name (like "PSA" or "HbA1c") and see how many FDA-cleared
lab tests already exist for it — and, optionally, whether it's also offered as a lab-developed
test in New York State. Meant to help you quickly gauge whether a biomarker is a crowded space
(lots of existing tests) or an open opportunity (few or none).

Two parts: a browser interface (no install) and a local cross-check backend (one-time Python
setup). **Run both — the backend is the default workflow, not an optional add-on.** It finds
real FDA approvals the browser alone structurally cannot see (see [Setup](#setup)). The browser
alone still works with zero setup — useful for a fast first look, or when Python isn't available
— but treat that as the reduced/fallback mode.

> Unfamiliar word (like "510(k)" or "LDT")? Check the **[Glossary](#glossary)** at the bottom.

## Contents

- [Setup](#setup)
- [Searching for a biomarker](#searching-for-a-biomarker)
- [Reading your results](#reading-your-results)
- [Sorting your results](#sorting-your-results)
- [Filtering and narrowing your results](#filtering-and-narrowing-your-results)
- [Exporting to Excel](#exporting-to-excel)
- [Checking a specific device's paperwork ("Measurand")](#checking-a-specific-devices-paperwork-measurand)
- [Automatic abbreviation lookup (UMLS and AI crosscheck)](#automatic-abbreviation-lookup-umls-and-ai-crosscheck)
- [Searching lab-developed tests (LDT) in New York State](#searching-lab-developed-tests-ldt-in-new-york-state)
- [Things to keep in mind](#things-to-keep-in-mind)
- [Glossary](#glossary)

## Setup

### Part 1 — the browser interface (always needed, no install)

1. Click the green **Code** button at the top of this page → **Download ZIP**. (Already have the
   folder? Skip this.)
2. Extract the ZIP (right-click → **Extract All** on Windows, double-click on Mac).
3. Double-click **`FDA510kBiomarkerSearch.html`** inside the extracted folder — it opens in your
   browser. Double-click the same file again any time you want to use the tool.

### Part 2 — the cross-check backend (default workflow, not optional)

The backend does two things the browser search structurally can't:

- **Reads bundled-panel reagents out of device PDFs.** Some devices measure a biomarker as part
  of a multi-antigen panel kit but never name it in FDA's searchable device data — only inside
  the device's own decision-summary PDF. The backend reads every device's cited "predicate" out
  of that PDF; if a device cites an already-confirmed match as its predicate, it's surfaced too,
  tagged **"inferred via predicate"** — shown separately, not counted in totals, since a cited
  predicate is a strong hint, not proof of an identical panel.
- **Precomputes the alternate-wordform check, so it's fast.** Same logic the browser runs live
  (see [Reading your results](#reading-your-results)), just computed once during the crawl
  instead of on every search — the browser alone has to make an extra network call per biomarker
  for this, which is noticeably slower.

510(k)-only, same as the browser search — no GUDID/UDI device-registration cross-check, no PMA
(Premarket Approval, a different FDA pathway for higher-risk Class III devices).

**Confirmed-match results work immediately for any biomarker — nothing to crawl first.** Only
the predicate-chain ("inferred via predicate") tier needs the one-time (then periodic) crawl
below, since it depends on having already read every scope device's PDF. That crawl doesn't need
to know which biomarkers you care about — it just builds the general device+PDF corpus (bounded
to a handful of relevant FDA review panels) that predicate-chain lookups draw on later.

**Setup** (one-time, from the repo root):
```bash
pip install -r indexer/requirements.txt
pip install -r server/requirements.txt
python -m indexer.crawl
```
Unlocks the predicate-chain tier — confirmed matches already work before this finishes. Takes a
while the first run (reading real PDFs, politely rate-limited); re-run periodically to pick up
newly-cleared devices (skips PDFs already fetched, so a re-run is fast).

**API keys — set them in the `.env` file at the repo root:**
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

**Running it:**
```bash
uvicorn server.main:app --reload
```
Resolves each biomarker's full name/synonyms automatically via UMLS, then a Tavily+local-LLM
crosscheck for whatever UMLS doesn't cover (see
[Automatic abbreviation lookup](#automatic-abbreviation-lookup-umls-and-ai-crosscheck)) — reads
these from your `.env` file, since this background process can't read the browser's Settings.

Then open **Settings** (gear icon) in the tool and enter the server's address (e.g.
`http://localhost:8000`) in **Local index server URL**. Searches now use the cross-checked
backend automatically, falling back to the plain browser search if it's blank or unreachable. A
banner reading "Running in fallback mode" shows until this is set.

### Part 3 — optional extras

- **[Automatic abbreviation lookup](#automatic-abbreviation-lookup-umls-and-ai-crosscheck)** —
  resolve an unrecognized biomarker abbreviation to its full name, via UMLS and/or a
  search-grounded AI crosscheck.
- **["Check Measurand"](#checking-a-specific-devices-paperwork-measurand)** — confirm what a
  specific device actually measures by reading its official FDA paperwork.
- **[LDT search](#searching-lab-developed-tests-ldt-in-new-york-state)** — check New York
  State's lab-developed-test database for biomarkers with few or no FDA-cleared devices.

## Searching for a biomarker

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

## Reading your results

A bar chart and a table show the same results two ways.

**Table columns:**

| Column | Meaning |
|---|---|
| Rank | Position in the current sort order (see [Sorting](#sorting-your-results)) |
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

## Sorting your results

- **Fewest approvals** (default) — least competition first, for spotting open opportunities.
- **Most recent approval** — most recently active first. Biomarkers with zero cleared devices
  have no date, so they sit at the bottom.

## Filtering and narrowing your results

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

  **Which panels are safe to rule out, for a lab biomarker search specifically:**

  | Almost always safe to rule out | Where real biomarker tests actually live |
  |---|---|
  | General, Plastic Surgery; Orthopedic; Cardiovascular; Radiology; Dental; Ear, Nose, and Throat; Ophthalmic; Anesthesiology; Physical Medicine; Gastroenterology-Urology; Obstetrics-Gynecology; General Hospital; Neurology | Immunology; Clinical Chemistry; Hematology; Microbiology; Pathology; Toxicology |

  The left column is hardware/surgical/imaging panels that never contain a lab assay — even
  blood-based biomarkers like troponin are classified under Clinical Chemistry, not
  Cardiovascular. The right column is exactly the scope the backend's predicate-chain crawl
  already bounds itself to (see `indexer/scope.py`), for the same reason: a genuine lab test
  realistically only ever lands in one of those six. Treat this as a strong default, not a
  guarantee — for an unfamiliar biomarker, it's still worth a glance at what's actually in a
  ruled-out panel's results before trusting the exclusion blindly.
- **Clear all filters** — resets date range, company filter, show-only list, and ruled-out
  panels together.

## Exporting to Excel

**Export to Excel** downloads a spreadsheet matching whatever's currently on screen (sort order
+ active filters). Sheets:

- **Search Info** — when/what/how this export was produced, so the file explains itself later.
- **Summary** — one row per biomarker, totals + Unique Applicants.
- **Biomarker Applicants** — one row per biomarker with its total submissions, unique-company
  count, and the actual company list.
- **Details** — one row per confirmed device, across every biomarker searched.
- **Unconfirmed Matches** — every unconfirmed candidate (from the backend's predicate-chain
  crawl), labeled by Match Type, kept separate so it's never mistaken for a confirmed result.

Running the LDT cross-check adds two more sheets, plus its own **Export to Excel** button.

## Checking a specific device's paperwork ("Measurand")

Every device row has a **Check Measurand** button: downloads the device's Decision Summary PDF
and checks the specific line stating what it actually measures — more authoritative than the
device name alone. Shows **Matches** or **No match**.

Most documents label this "Measurand" or "Analyte"; multi-parameter devices (e.g. hematology
analyzers) have neither, so the tool falls back to "Type of Test" or "Intended Use" instead.

**One-time setup required:** FDA's site blocks direct browser access to this PDF, so this needs
a small free Cloudflare "Worker" go-between. See **[worker/README.md](worker/README.md)**
(~5 minutes, no coding), or paste a ready-made shared Worker URL from there to skip setup
entirely. Until then, the button tells you a Worker URL is needed in Settings. Skipping this
setup doesn't affect anything else — it's an optional extra layer of confirmation.

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

Setup, via `.env` (see [Setup](#setup)): `TAVILY_API_KEY` from
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
keeps a public list, searchable here too.

**Directly:** click the **LDT** tab and search the same way.

**Automatically after an FDA search:** if any biomarker showed **2 or fewer** FDA-cleared
devices, a button appears offering to check all of them against New York's list in one pass — a
low-but-nonzero count can still point to a real LDT-only opportunity, not just a strict zero.

**One-time setup required:** same reason as Measurand above — see
**[worker/README.md](worker/README.md)**, or use a shared Worker URL from there.

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
- Everything you type and any browser Settings (Worker URLs, API keys) stay in your own browser
  — nothing is sent anywhere except directly to the FDA and, if configured, New York's site, the
  FDA paperwork site, NLM's UMLS database, Tavily, and your own local backend/AI model. Backend
  API keys in `.env` stay on your machine and are gitignored.

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

## Tech (for anyone who *does* code)

Plain HTML/CSS/JS, no build tooling. Uses [Chart.js](https://www.chartjs.org/) and
[SheetJS](https://sheetjs.com/) from a CDN. See [worker/README.md](worker/README.md) for the two
optional Cloudflare Worker proxies — UMLS needs no proxy, its API sends CORS headers allowing
direct browser calls. The cross-check backend (`indexer/` + `server/`) is a separate Python
project (see [Setup](#setup)); both load config from a `.env` file at the repo root via
`python-dotenv`.

## License

Modified MIT (see [LICENSE](LICENSE)) — free to use, modify, and share, including internally at
a company. The one thing it doesn't allow is selling the software itself or bundling it into
something sold, without the copyright holder's permission.
