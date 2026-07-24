# Biomarker Search

**What this is, in plain terms:** a tool that lets you type in a biomarker name (like "PSA" or
"HbA1c") and see how many FDA-cleared lab tests already exist for it — and, optionally, whether
it's also offered as a lab-developed test in New York State. It's meant to help you quickly
gauge whether a biomarker is a crowded space (lots of existing tests) or an open opportunity
(few or none).

You do **not** need to know how to code to use this. You don't need to install anything. It
runs entirely in your web browser (Chrome, Edge, Firefox, Safari — whatever you already use).

> If a word here is unfamiliar (like "510(k)" or "LDT"), check the **[Glossary](#glossary)** at
> the bottom — it explains every technical and regulatory term used in this guide.

## Contents

- [Getting started](#getting-started)
- [Searching for a biomarker](#searching-for-a-biomarker)
- [Reading your results](#reading-your-results)
- [Sorting your results](#sorting-your-results)
- [Filtering by date](#filtering-by-date)
- [Exporting to Excel](#exporting-to-excel)
- [Checking a specific device's paperwork ("Measurand")](#checking-a-specific-devices-paperwork-measurand)
- [Searching lab-developed tests (LDT) in New York State](#searching-lab-developed-tests-ldt-in-new-york-state)
- [If nothing turns up](#if-nothing-turns-up)
- [Things to keep in mind](#things-to-keep-in-mind)
- [Glossary](#glossary)

## Getting started

1. Go to the top of this page and click the green **Code** button, then **Download ZIP**.
   (If someone already sent you a folder with these files instead, skip this step.)
2. Find the downloaded ZIP file (usually in your **Downloads** folder) and unzip/extract it —
   right-click it and choose **Extract All** (Windows) or double-click it (Mac).
3. Open the extracted folder and double-click **`FDA510kBiomarkerSearch.html`**. It will open
   in your default web browser and you're ready to go.

That's it — there is no installation, no account to create, and no software to set up. Every
time you want to use the tool again, just double-click that same file.

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
| Not Cleared | Almost always 0 — the FDA's public database only lists devices that *were* cleared, not ones that were rejected |

Click anywhere on a row to expand it and see the individual devices behind that number: device
name, the company that submitted it, the decision, the approval date, a link to the official
FDA page, and a **Check Measurand** button (explained [below](#checking-a-specific-devices-paperwork-measurand)).

**Tags you might see next to a biomarker name:**

- **Broad match** — no exact match was found, so the tool searched more loosely (ignoring word
  order)
- **Antigen-only match** — same as above, but it also ignored the antibody class (IgG/IgA/IgM)
- **Expanded-name match** — the abbreviation itself wasn't found, so the tool searched using
  the full spelled-out name instead
- **N possible panel matches** — no confirmed match, but the tool found device(s) that mention
  a bundle/panel of tests in a related area. These are *not* counted in the numbers above
  because the FDA's own records don't spell out which individual biomarkers are inside the
  bundle — you'd need to open the device's paperwork to check by hand (the **Check Measurand**
  button on that device can help)

None of these tags mean the result is wrong — they just tell you how confident the match is,
so an exact match is more reliable than an "expanded-name match."

## Sorting your results

Above the table, there are two buttons:

- **Fewest approvals** (the default) — puts biomarkers with the *least* competition at the
  top. Useful for spotting open opportunities.
- **Most recent approval** — puts biomarkers whose *newest* cleared device is most recent at
  the top. Useful for spotting where the FDA has been recently active. Biomarkers with zero
  cleared devices have no date to sort by, so they always sit at the bottom in this view.

## Filtering by date

Still above the table, you'll find two small **From** / **To** boxes where you can pick a
month and year. Once you pick either one, the table (and the chart, and the numbers) update to
count only devices cleared within that window — handy for questions like "how many of these
were cleared in just the last 5 years?" Click **Clear** to go back to showing everything.

## Exporting to Excel

Click **Export to Excel** at any time after a search to download a spreadsheet file. It always
matches whatever is currently on screen — the same sort order and the same date filter, if
you've set one. It contains:

- **Summary** — one row per biomarker with its totals.
- **Details** — one row per individual device found, across every biomarker you searched.

## Checking a specific device's paperwork ("Measurand")

Every device row has a **Check Measurand** button. Clicking it downloads that device's actual
FDA paperwork (the "Decision Summary," a PDF) and looks for the specific line stating what the
test actually measures — a more authoritative check than the device's name alone, since names
can be misleading or abbreviated. The result appears right there, marked either **Matches** or
**No match**.

**One-time setup required:** the FDA's paperwork website doesn't allow this tool to read it
directly for security reasons on FDA's side, so this feature needs a small, free
"go-between" service (called a "Worker") that you set up once. It takes about 5 minutes and
needs no coding — see **[worker/README.md](worker/README.md)** for the exact clicks. Until you
do this, clicking **Check Measurand** will tell you it needs a Worker URL in Settings.

If you skip this setup, every other part of the tool still works fine — this is an optional
extra layer of confirmation.

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
**[worker/README.md](worker/README.md)** for the walkthrough. Until then, this tab will tell
you to add a Worker URL in Settings first.

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
- Everything you type and any settings you enter (like a Worker URL) are saved only inside your
  own browser, on your own computer — nothing is sent anywhere except directly to the FDA (and,
  if you set them up, to New York's site and the FDA paperwork site).

## Glossary

| Term | Plain-English meaning |
|---|---|
| **Biomarker** | A measurable substance in the body (a protein, antibody, hormone, etc.) used to test for a disease or condition. |
| **FDA 510(k)** | A pathway the FDA uses to clear most lab tests and medical devices for sale, by showing a new device is "substantially equivalent" to one already on the market. Each cleared device gets a reference number starting with **K** (e.g. `K123456`). |
| **De Novo (DEN)** | A different FDA pathway, used for genuinely novel devices that have nothing existing to compare against. These get a reference number starting with **DEN** instead of K. This tool treats them the same as 510(k) devices in its results. |
| **Cleared / Approved** | The FDA decided the device is "Substantially Equivalent" and it can be legally sold. |
| **LDT (Lab-Developed Test)** | A test that a single laboratory designs, builds, and runs in-house, rather than buying a ready-made FDA-cleared kit. These are regulated differently than FDA-cleared devices — some states, like New York, require their own separate approval for them. |
| **Decision Summary** | The FDA's official write-up explaining why a specific device was cleared — usually a PDF, a few pages long, with a standard structure. |
| **Measurand** | The technical term (used in that FDA paperwork) for exactly what a test measures — e.g. "Anti-GAD65 antibodies in human serum." |
| **Worker** | A small, free program that runs on Cloudflare's servers (not your computer) and acts as a go-between, letting this tool reach a website that would otherwise block it directly. You set one up once by copy-pasting code into a web page — no programming needed. See [worker/README.md](worker/README.md). |
| **API / API key** | A way for one computer program to ask another for data automatically (in this case, this tool asking the FDA's database for results). An "API key" is just a free password that raises how many searches per day you're allowed — you don't need one to use this tool, it just helps if you're doing a lot of searching. |
| **openFDA** | The FDA's own public, free database that this tool queries. |

## Tech (for anyone who *does* code)

Plain HTML/CSS/JS, no build tooling, no dependencies to install. Uses
[Chart.js](https://www.chartjs.org/) for the chart and [SheetJS](https://sheetjs.com/) for
Excel export, both loaded from a CDN. See [worker/README.md](worker/README.md) for the two
optional Cloudflare Worker proxies.
