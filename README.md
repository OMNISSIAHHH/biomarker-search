# Biomarker Search

**What this is, in plain terms:** a tool that lets you type in a biomarker name (like "PSA" or
"HbA1c") and see how many FDA-cleared lab tests already exist for it — and, optionally, whether
it's also offered as a lab-developed test in New York State. It's meant to help you quickly
gauge whether a biomarker is a crowded space (lots of existing tests) or an open opportunity
(few or none).

This has two parts: a browser interface (no install, no coding) and a local cross-check backend
(a one-time Python setup). **Running both together is the default, intended way to use this
tool** — not an optional add-on layered on top. The backend finds real FDA approvals that the
browser interface structurally cannot see on its own (see [Setup](#setup) below). The browser
interface also works entirely on its own with zero setup, which is genuinely useful for a fast
first look or when Python isn't available — but treat that as the reduced/fallback mode, not
the normal way to run this.

> If a word here is unfamiliar (like "510(k)" or "LDT"), check the **[Glossary](#glossary)** at
> the bottom — it explains every technical and regulatory term used in this guide.

## Contents

- [Setup](#setup)
- [Searching for a biomarker](#searching-for-a-biomarker)
- [Reading your results](#reading-your-results)
- [Sorting your results](#sorting-your-results)
- [Filtering and narrowing your results](#filtering-and-narrowing-your-results)
- [Exporting to Excel](#exporting-to-excel)
- [Checking a specific device's paperwork ("Measurand")](#checking-a-specific-devices-paperwork-measurand)
- [Automatic abbreviation lookup (UMLS or a local AI model)](#automatic-abbreviation-lookup-umls-or-a-local-ai-model)
- [Searching lab-developed tests (LDT) in New York State](#searching-lab-developed-tests-ldt-in-new-york-state)
- [Things to keep in mind](#things-to-keep-in-mind)
- [Glossary](#glossary)

## Setup

### Part 1 — the browser interface (always needed, no install)

1. Go to the top of this page and click the green **Code** button, then **Download ZIP**.
   (If someone already sent you a folder with these files instead, skip this step.)
2. Find the downloaded ZIP file (usually in your **Downloads** folder) and unzip/extract it —
   right-click it and choose **Extract All** (Windows) or double-click it (Mac).
3. Open the extracted folder and double-click **`FDA510kBiomarkerSearch.html`**. It will open
   in your default web browser. Every time you want to use the tool again, just double-click
   that same file.

### Part 2 — the cross-check backend (default workflow — do this next, not "later")

This is the default, intended way to run this tool — not an advanced add-on for power users.
Part 1 alone is a reduced/fallback mode: it works with no setup at all, which is genuinely
useful for a fast first look or when Python isn't available, but it misses real approvals in
ways that are structural, not edge cases (see below). This local backend is what makes results
reliable, and it's faster, not slower, once it's set up. There is no list anywhere of "which
biomarkers this tool knows about" — every term you search is resolved automatically (by AI,
same idea as [Automatic abbreviation lookup](#automatic-abbreviation-lookup-umls-or-a-local-ai-model)
below) and its results are cached, so a repeat search is instant and a first-time search for
*any* biomarker — one at a time or hundreds pasted in at once — just works, no list to maintain
first. It does two different kinds of things:

**Finds results Part 1 structurally can't**, by reading every candidate device's
decision-summary PDF, not just its searchable device-name text:

- **Bundled panel reagents.** Some devices measure a biomarker as part of a multi-antigen panel
  kit, but never name that biomarker anywhere in FDA's own searchable device data — the only
  place it's stated is inside the device's own decision-summary PDF. This backend reads every
  device's cited "predicate" (the earlier device it claims to be equivalent to) out of that PDF,
  and if a device cites an already-confirmed match as its predicate, it's surfaced too — tagged
  **"inferred via predicate"**, shown separately from confirmed results and not counted in the
  totals, since a cited predicate is a strong hint, not proof of an identical panel, so it's
  still worth a manual check.

**Precomputes results Part 1 already finds, just faster.** The **alternate wordform match** and
**found via device registry** checks (see [Reading your results](#reading-your-results)) don't
need any PDF reading — they're identical logic to the plain browser search, just run once
during the crawl instead of fresh on every search. Without this backend running, the browser
has to make several extra network calls per biomarker to compute these on the spot, which
measurably slows it down (roughly 2-3x per biomarker in testing); the local server instead
reads the already-computed answer straight from its local file, so search speed there doesn't
depend on how many live FDA API calls a term happens to need.

This is 510(k)-only, same as the browser search — it does not include PMA (Premarket Approval,
for higher-risk Class III devices), which is a different FDA regulatory pathway outside this
tool's scope.

**Confirmed-match and device-registry results work immediately for any biomarker, with nothing
to crawl first.** The one thing that does need a one-time (well, periodic) crawl is the
predicate-chain panel-reagent tier above, since it depends on having already read every scope
device's decision-summary PDF — fetching and reading thousands of PDFs is too slow to do live
during a search. Running that crawl doesn't need to know which biomarkers you care about either
— it just builds the general device+PDF corpus (bounded to a handful of relevant FDA review
panels) that the predicate-chain lookup then draws on for whatever you end up searching.

**Setup** (one-time, from the repo root, in a terminal):
```bash
pip install -r indexer/requirements.txt
pip install -r server/requirements.txt
python -m indexer.crawl
```
This step is what unlocks the predicate-chain ("inferred via predicate") tier — searching
confirmed matches and the device registry already works even before this finishes. The crawl
can take a while the first time (it's reading real PDFs one at a time, politely rate-limited) —
it prints progress as it goes. **Re-run it periodically** to pick up newly-cleared devices (it
skips PDFs it's already fetched, so a re-run is fast). Add `--api-key YOUR_OPENFDA_KEY` to go
faster.

**Running it:**
```bash
uvicorn server.main:app --reload
```
The server resolves each biomarker's full name/synonyms automatically via AI, the same as
[Automatic abbreviation lookup](#automatic-abbreviation-lookup-umls-or-a-local-ai-model) below —
but since this is a separate background process, it can't read the browser's Settings, so
configure it with environment variables instead, e.g.:
```bash
LOCAL_LLM_URL=http://localhost:11434 LOCAL_LLM_MODEL=qwen3:4b uvicorn server.main:app --reload
```
or, using UMLS instead:
```bash
UMLS_API_KEY=your-key-here uvicorn server.main:app --reload
```
Then open **Settings** (gear icon) in the tool itself and enter the server's address (e.g.
`http://localhost:8000`) in **Local index server URL**. From then on, searches automatically use
the cross-checked results when the server is running, and fall back to the plain browser search
whenever it's blank or not running — nothing else changes. A banner in the tool itself says
"Running in fallback mode" until this is set.

### Part 3 — optional extras

Everything below is opt-in on top of Parts 1 and 2, each with its own short setup, covered in
full later in this guide:

- **[Automatic abbreviation lookup](#automatic-abbreviation-lookup-umls-or-a-local-ai-model)** —
  look up the full name of a biomarker abbreviation this tool doesn't already recognize, via
  either UMLS (a real medical terminology database, slower to set up) or a local AI model (no
  license or waiting, but a guess instead of a lookup).
- **["Check Measurand"](#checking-a-specific-devices-paperwork-measurand)** — confirm what a
  specific device actually measures by reading its official FDA paperwork, not just its name.
- **[LDT search](#searching-lab-developed-tests-ldt-in-new-york-state)** — check New York
  State's separate database of lab-developed tests, for biomarkers with 0 FDA-cleared devices.

## Searching for a biomarker

1. Make sure the **FDA 510(k)** tab is selected near the top (it's the default).
2. In the big text box, type the biomarker name(s) you want to look up. You can enter more
   than one at a time — one per line, or separated by commas:
   ```
   HbA1c
   Troponin
   PSA
   BNP
   ```
3. Click the **Search** button.
4. Wait a few seconds — the tool is asking the FDA's public database, one biomarker at a
   time, whether any cleared lab tests mention it.

You can type biomarker names the way they're normally written, including antibody names like
"Anti-GAD65" or ones with Greek letters like "Anti-β2-GP1" — the tool automatically handles
both.

## Reading your results

After a search, you'll see a bar chart and a table, both showing the same information two
ways.

**The table** has one row per biomarker you searched, with these columns:

| Column | What it means |
|---|---|
| Rank | Its position in the current sort order (see [Sorting](#sorting-your-results)) |
| Biomarker | The name you typed. If the tool had to search more loosely to find anything, a small tag appears next to it explaining how (see below) |
| Total Submissions | How many FDA filings mention this biomarker |
| Cleared (Approved) | How many of those were actually cleared by the FDA. A **red** number means 10 or more — a more crowded, competitive space. A **green** number means fewer than 10 |
| Unique Applicants | How many *distinct companies* are behind those submissions. If this is lower than Total Submissions, at least one company filed more than once for this biomarker — worth a look with the [Submitted by filter](#filtering-and-narrowing-your-results) below |

Click anywhere on a row to expand it and see the individual devices behind that number: device
name, the company that submitted it, the decision, the approval date, a link to the official
FDA page, and a **Check Measurand** button (explained [below](#checking-a-specific-devices-paperwork-measurand)).

**Tags you might see next to a biomarker name:**

- **Broad match** — no exact match was found, so the tool searched more loosely (ignoring word
  order)
- **Antigen-only match** — same as above, but it also ignored the antibody class (IgG/IgA/IgM)
- **UMLS-resolved match** — none of the above found anything either, so the abbreviation's
  spelled-out medical name was looked up automatically instead (see
  [Automatic abbreviation lookup](#automatic-abbreviation-lookup-umls-or-a-local-ai-model)
  below)
- **AI-suggested match** — same situation as above, but resolved by a local AI model instead of
  UMLS. This is a *generated guess*, not a database lookup — a wrong answer can look just as
  confident as a right one, so treat this one with more skepticism than a UMLS-resolved match
  and double-check it, e.g. via **Check Measurand**
- **Fused-word match** — FDA sometimes writes "Anti" and the antigen as one run-together word
  with no space or hyphen (e.g. "Anticardiolipin"). The tool automatically tries that fused
  form for any antibody-style search, so this can show up even for terms with no special
  handling built in ahead of time
- **Alternate wordform match** — FDA device names aren't consistent about spacing/hyphens
  either (e.g. some devices write "DS DNA" split apart where you'd type "dsDNA" fused). The
  tool automatically tries splitting apart fused words, swapping hyphens for spaces (and back),
  and fully fusing multi-word terms — for any search, not just ones with special handling
  built in ahead of time
- **N found via device registry** — the tool also checks FDA's separate UDI/GUDID
  device-registration database, whose free-text device descriptions are sometimes far more
  detailed than a 510(k) record's own device name (bundled multi-antigen kits often list every
  component antigen there, even when the 510(k) record never names them). Not counted in the
  numbers above — a single 510(k) clearance can cover a whole family of related products, so a
  device showing up this way doesn't always mean *that exact device* contains the biomarker,
  only that something under its clearance does. Worth a manual check.

None of these tags mean the result is wrong — they just tell you how confident the match is,
so an exact match is more reliable than a "UMLS-resolved match" or an "AI-suggested match."

## Sorting your results

Above the table, there are two buttons:

- **Fewest approvals** (the default) — puts biomarkers with the *least* competition at the
  top. Useful for spotting open opportunities.
- **Most recent approval** — puts biomarkers whose *newest* cleared device is most recent at
  the top. Useful for spotting where the FDA has been recently active. Biomarkers with zero
  cleared devices have no date to sort by, so they always sit at the bottom in this view.

## Filtering and narrowing your results

Above the table, you'll find several filters. All of them work together, all of them update
the table/chart/numbers together (nothing needs a re-search), and all of them carry over into
the Excel export automatically.

**By date.** Two small **From** / **To** boxes let you pick a month and year — the table then
only counts devices cleared within that window. Handy for questions like "how many of these
were cleared in just the last 5 years?" Click **Clear** to reset just this one.

**By company ("Submitted by").** A dropdown listing every company that shows up anywhere in
your current results. Pick one to narrow every biomarker's device list down to just that
company's submissions — useful for seeing a single company's pattern across several
biomarkers, or confirming the "Unique Applicants" gap mentioned above.

**"Show only" a specific biomarker or company.** Type a name into this box and click **Add** —
the view narrows down to *only* whatever matches (searching either a biomarker's own name or
an applicant's name), everything else is hidden. Each thing you add shows up as a small
removable tag; click its **×** to bring the rest back.

**Rule out an FDA review panel.** Short abbreviations can collide with something completely
unrelated — "RF" matches both *Rheumatoid Factor* (a real lab test) and *Radio Frequency*
(ablation devices, a totally different product category), since it's the literal same two
letters. Every FDA device is routed to a review panel when it's cleared (Immunology, Clinical
Chemistry, General Surgery, and so on) — click **Rule out FDA review panel** to open a list of
every panel actually present in your current results, and check the ones that clearly don't
belong (e.g. ruling out "General, Plastic Surgery" for a lab-test search) to clean up the
count. Nothing is ruled out automatically — you're always the one deciding, since only you can
judge which panels make sense to exclude for a given biomarker. Use **Clear all review
panels** (inside that same dropdown) to undo just this filter.

**Clearing everything at once.** Click **Clear all filters** to reset the date range,
company filter, "show only" list, and ruled-out panels together in one click.

## Exporting to Excel

Click **Export to Excel** at any time after a search to download a spreadsheet file. It always
matches whatever is currently on screen — the same sort order and every active filter — so two
exports from the same search can look very different if you've narrowed things down in
between. It contains:

- **Search Info** — a record of exactly how this export was produced: when, which biomarkers,
  the sort order, and the state of every filter. Meant so the file explains itself later,
  without needing to remember the browser session it came from.
- **Summary** — one row per biomarker with its totals, including Unique Applicants.
- **Biomarker Applicants** — one row per biomarker across your whole search, with its total
  submissions, how many unique companies filed them, and the actual list of those companies.
  A quick way to see who the players are for a given biomarker without building a pivot table
  by hand.
- **Details** — one row per confirmed individual device found, across every biomarker you
  searched.
- **Unconfirmed Matches** — every unconfirmed candidate (devices found via the cross-check
  backend's predicate-chain crawl, and devices found via the device registry), each labeled with
  its own Match Type column, kept in their own sheet so they're never mistaken for a confirmed
  result.

If you ran the LDT cross-check (see below), two more sheets are added with those results —
there's also a second **Export to Excel** button at the bottom of that table specifically, in
case that's the last thing you looked at.

## Checking a specific device's paperwork ("Measurand")

Every device row has a **Check Measurand** button. Clicking it downloads that device's actual
FDA paperwork (the "Decision Summary," a PDF) and looks for the specific line stating what the
test actually measures — a more authoritative check than the device's name alone, since names
can be misleading or abbreviated. The result appears right there, marked either **Matches** or
**No match**.

Most documents label this field "Measurand" or "Analyte," but multi-parameter devices like
hematology analyzers don't have one at all — for those, the tool automatically falls back to
whatever section actually lists the parameters tested (e.g. "Type of Test" or "Intended Use"),
so you still get a useful answer either way.

**One-time setup required:** the FDA's paperwork website doesn't allow this tool to read it
directly for security reasons on FDA's side, so this feature needs a small, free
"go-between" service (called a "Worker") that you set up once. It takes about 5 minutes and
needs no coding — see **[worker/README.md](worker/README.md)** for the exact clicks, or paste
in a ready-made shared Worker URL from there if you'd rather skip setup entirely. Until you do
either, clicking **Check Measurand** will tell you it needs a Worker URL in Settings.

If you skip this setup, every other part of the tool still works fine — this is an optional
extra layer of confirmation.

## Automatic abbreviation lookup (UMLS or a local AI model)

There is no built-in, hand-curated list of biomarker abbreviations — every term's full medical
name and synonyms (needed when the abbreviation itself, like "GADA" or "cTnT," doesn't appear
verbatim in FDA paperwork) are resolved automatically instead. Two optional ways exist to do
this; if neither is set up, the tool still finds whatever the exact/broad/antigen-only tiers
above can on their own, just without an alternate name to fall back on.

**Option 1 — UMLS** (a real database, slower to set up): go to
**[uts.nlm.nih.gov/uts/license](https://uts.nlm.nih.gov/uts/license)**, sign in with an
identity provider (Login.gov works if you don't have one already), and agree to the license
terms — this is a real license request, so the National Library of Medicine reviews it by
hand and it can take **up to 3 business days** before your account is approved. Once approved,
sign in, open your profile, and generate an API key. Paste that key into **Settings** (gear
icon) → **UMLS API key**. Unlike the LDT and Measurand features, this one needs no separate
Worker setup — paste the key and it works. A match found this way is flagged
**UMLS-resolved match** since nobody has manually confirmed the looked-up name is correct —
worth a quick sanity check, e.g. via **Check Measurand**.

**Option 2 — a local AI model** (no license or waiting, but a guess instead of a lookup):
install [Ollama](https://ollama.com), pull a small model (e.g. `ollama pull qwen3:4b`), and
paste its address into **Settings** → **Local LLM URL** (usually `http://localhost:11434`) and
the exact model name into **Local LLM model**. When both UMLS and a local model are configured,
the local model is tried first. A match found this way is flagged **AI-suggested match** — a
generated guess, not a database entry, so it deserves more skepticism than a UMLS-resolved
match: a wrong answer from a model can sound exactly as confident as a right one. Always worth
a sanity check, e.g. via **Check Measurand**, before trusting it.

**Running Ollama on a different PC than the one you use the tool from:** `http://localhost:11434`
only works when Ollama and the browser tool (or backend server) are on the *same* machine.
Across machines on the same network:
1. On the Ollama PC, set the environment variable `OLLAMA_HOST=0.0.0.0:11434` and restart
   Ollama — by default it only listens on `localhost` and refuses connections from elsewhere.
2. Allow inbound traffic on port 11434 through its firewall, e.g. on Windows:
   ```powershell
   New-NetFirewallRule -DisplayName "Ollama" -Direction Inbound -LocalPort 11434 -Protocol TCP -Action Allow
   ```
3. Find that PC's LAN IP (`ipconfig` on Windows, `ifconfig`/`ip addr` on Mac/Linux) and use
   `http://<that-ip>:11434` as the Local LLM URL / `LOCAL_LLM_URL` instead of `localhost`.
4. Test reachability first from the other machine, e.g.
   `Invoke-WebRequest http://<that-ip>:11434/api/tags` (PowerShell) or
   `curl http://<that-ip>:11434/api/tags` — it should return a 200 with a JSON list of models,
   the same as it does locally.

If the two machines aren't on the same network (e.g. one is remote/cloud), reaching Ollama
needs something more than a firewall rule — a VPN or port-forwarding — which is outside the
scope of this guide.

These two Settings fields configure the browser tool's own last-resort lookup, used only when
the exact/broad/antigen-only tiers above found nothing. The cross-check backend (see
[Setup](#setup)) uses the same two engines for every search, not just as a last resort — but
since it's a separate background process with no access to the browser's Settings, it's
configured with environment variables instead when you start it.

## Searching lab-developed tests (LDT) in New York State

Sometimes a biomarker shows 0 FDA-cleared devices, but that doesn't necessarily mean nobody
tests for it — it might be offered as a "lab-developed test" (a test a specific lab built
in-house, run under a different kind of oversight than FDA clearance; see the
[Glossary](#glossary)). New York State keeps a public list of these, and this tool can search
it too.

**To search it directly:** click the **LDT** tab (next to FDA 510(k)) and search the same way.

**To check automatically after an FDA search:** if any of your biomarkers showed 0 FDA-cleared
devices, a button appears below the FDA results offering to check all of them against New
York's list in one pass.

**One-time setup required:** same reason as the Measurand feature above — New York's website
needs a small free Worker set up once before this will work. See
**[worker/README.md](worker/README.md)** for the walkthrough, or grab a ready-made shared
Worker URL from there instead if you'd rather skip setup entirely. Until then, this tab will
tell you to add a Worker URL in Settings first.

### If nothing turns up

New York's list only covers labs that hold a New York permit — a small slice of all the labs
in the country. If a biomarker shows "No matching LDTs found," that doesn't prove nobody offers
it — it just means no New York-permitted lab does. In that case, a **Search Google for "&lt;name&gt;
LDT"** link appears, which opens a normal Google search in a new tab — this often turns up the
actual lab offering it (national reference labs like ARUP, Mayo Clinic Laboratories, or LabCorp
frequently show up this way).

## Things to keep in mind

- **"Cleared"** here always means the FDA's "Substantially Equivalent" decision — the normal
  outcome for an approved device in this dataset.
- Results are capped at 300 devices per biomarker so a single search doesn't take forever. If a
  biomarker has more than that, the total count shown is still accurate, but only the first
  300 are listed and exported.
- This tool is for research purposes only. It is not medical advice and should never be used
  to make decisions about patient care. Always double-check anything important directly on the
  [FDA's own website](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfPMN/pmn.cfm).
- Everything you type and any settings you enter (like a Worker URL or API key) are saved only
  inside your own browser, on your own computer — nothing is sent anywhere except directly to
  the FDA (and, if you set them up, to New York's site, the FDA paperwork site, NLM's UMLS
  database, and your own local backend/AI model).

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

Plain HTML/CSS/JS, no build tooling, no dependencies to install. Uses
[Chart.js](https://www.chartjs.org/) for the chart and [SheetJS](https://sheetjs.com/) for
Excel export, both loaded from a CDN. See [worker/README.md](worker/README.md) for the two
optional Cloudflare Worker proxies. The UMLS lookup needs no proxy — its API sends CORS headers
that allow calling it directly from the browser. The cross-check backend (`indexer/` + `server/`)
is a separate Python project — see [Setup](#setup) above.

## License

Modified MIT (see [LICENSE](LICENSE)) — free to use, modify, and share, including internally
at a company. The one thing it doesn't allow is selling the software itself or bundling it
into something sold, without the copyright holder's permission.
