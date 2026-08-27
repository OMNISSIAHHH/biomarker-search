# Proxy Workers

No coding experience needed for this either — it's copy-paste, entirely through your web
browser, on Cloudflare's free plan (no credit card required). It takes about 5 minutes per
Worker.

**What's a "Worker" and why do I need one?** Three features of this tool — searching New York's
lab-developed-test list, searching Quest Diagnostics' test catalog, and the "Check Measurand"
button — need to read data from a website that, for its own security reasons (or, for Quest,
an explicit origin allowlist), refuses to hand that data directly to a page running in your
browser. A Worker is a small, free helper program (hosted by Cloudflare, not your own computer)
that fetches the data on the tool's behalf and passes it along. You never see or touch its code
beyond pasting it in once during setup.

Two other LDT-adjacent sources — **ARUP** and **LabCorp** — need no Worker at all; both allow
direct cross-origin requests from this tool, so they're always on with zero setup.

This folder has three of these small programs:

| Worker | Fetches from | Powers |
|---|---|---|
| `ldt-proxy.js` | NY State Wadsworth Center's lab-developed-test list | The **LDT** search tab, NY State source |
| `quest-proxy.js` | Quest Diagnostics' test directory | The **LDT** search tab, Quest source |
| `fda-pdf-proxy.js` | The FDA's own website (Decision Summary PDFs) | The **Check Measurand** button on an FDA search result |

All three are optional — the main **FDA 510(k)** search, and the ARUP/LabCorp LDT sources,
work fine with none of them set up. Only set up the one(s) for the feature(s) you actually
want; skip the others if you don't need them.

**Before deploying `quest-proxy.js`, read the note in Settings (gear icon) next to the Quest
proxy field** — Quest's Terms of Use restrict automated/commercial reuse of their test-directory
content beyond noncommercial/educational purposes without written permission. This is a real
consideration, not just a technical one.

## Don't want to set one up? Use these instead

Paste these directly into **Settings** (gear icon) and skip the deploy steps below entirely:

```
LDT proxy Worker URL:     https://ldt-proxy.francis121026.workers.dev
FDA PDF proxy Worker URL: https://fda-pdf-proxyjs.francis121026.workers.dev
```

These are donated, shared instances — convenient to try the tool immediately, but they run on
one person's free Cloudflare account with a shared daily request limit across everyone using
them, and no uptime guarantee. If you're using this tool regularly or for real work, deploy
your own (below) — it's free, it's yours alone, and it takes about the same 5 minutes either
way. There's no donated shared instance for `quest-proxy.js` yet — deploy your own if you want
the Quest source (see the ToU note above first).

## Deploy (no local Node/wrangler needed)

This takes about 5 minutes per Worker, entirely in the browser, on Cloudflare's free plan (no
credit card required). Cloudflare's dashboard wording shifts slightly between account types
and over time — if a button doesn't say the exact text below, look for the button that
matches the *description* next to it; the flow itself is stable. Repeat these steps once for
each Worker you want (they're independent — different name, different code, different URL).

**1. Create a Cloudflare account (skip if you already have one)**

Go to **[dash.cloudflare.com/sign-up](https://dash.cloudflare.com/sign-up)** and sign up with
an email address. No payment info is needed for what we're doing here.

**2. Open the Workers section**

Log in at **[dash.cloudflare.com](https://dash.cloudflare.com)**. In the left sidebar, click
**Workers & Pages** (if you don't see a sidebar, click the hamburger/menu icon top-left first).

**3. Pick a `workers.dev` subdomain (first Worker only, one-time)**

If this is the very first Worker on your account, Cloudflare will ask you to choose a
subdomain, e.g. typing `francis-tools` gives you `*.francis-tools.workers.dev` for every
Worker you ever create. Pick anything available and confirm — you can't easily change this
later, but it doesn't matter what you pick. Skip this step if you've already deployed one
Worker before (e.g. you're now adding the second one).

**4. Create the Worker**

Click **Create application** (or just **Create**, depending on what you see) → choose
**Create Worker** (sometimes labeled **"Hello World" Worker** or similar — you want the
plain/blank starter, not a framework template like Next.js or a specific gallery example).
Give it a name when prompted — e.g. `ldt-proxy` or `fda-pdf-proxy` (this becomes part of the
URL, so keep it short — the boxes usually accept `-` but not spaces). Click **Deploy** to
create it with its placeholder "Hello World" code — you'll replace that code next.

**5. Replace the code**

On the Worker's page, click **Edit code** (sometimes shown as a `</>` icon, or "Edit" in a
dropdown). This opens a browser-based code editor showing a file, usually named `worker.js`
or `index.js`, containing placeholder `Hello World` code.

- Select **all** the existing text in that file (Ctrl+A / Cmd+A) and delete it.
- Open the file you want from this repo — [`ldt-proxy.js`](ldt-proxy.js),
  [`quest-proxy.js`](quest-proxy.js), or [`fda-pdf-proxy.js`](fda-pdf-proxy.js) — copy its
  **entire contents**, and paste it into the editor in place of the placeholder.

**6. Deploy**

Click **Save and deploy** (or **Deploy**, top-right of the editor). Wait for the confirmation
that it deployed successfully.

**7. Get the URL and verify it works**

Go back to the Worker's main page (leave the code editor) — you'll see its URL near the top,
looking like:

```
https://ldt-proxy.<your-subdomain>.workers.dev
```
or
```
https://quest-proxy.<your-subdomain>.workers.dev
```
or
```
https://fda-pdf-proxy.<your-subdomain>.workers.dev
```

Test it directly in a new browser tab before wiring it into the tool:

- **LDT proxy**: append `?q=GADA` — you should see a page of JSON starting with
  `{"term":"GADA","total":...`.
- **Quest proxy**: append `?q=Troponin` — you should see a page of JSON starting with
  `{"term":"Troponin","total":...`.
- **FDA PDF proxy**: append `?k=K051061` — your browser should open/download an actual PDF
  (a real Decision Summary). If you see JSON like `{"error":...}` instead, read the message —
  `Missing or malformed required query parameter: k` just means you forgot `?k=...`.

If instead you see an error page or blank response, see **Troubleshooting** below.

**8. Wire it into the tool**

Open `FDA510kBiomarkerSearch.html` in a browser, click the gear icon (Settings), and paste the
Worker's base URL (**without** the `?q=...`/`?k=...` part you added to test) into the matching
field — **LDT proxy Worker URL (NY State)**, **Quest proxy Worker URL**, or **FDA PDF proxy
Worker URL**. Then either switch to the **LDT** tab and search a biomarker (with the
corresponding source checked in the "Data sources" row), or run an FDA search and click **Check
Measurand** on a result, to confirm.

### Troubleshooting

| Symptom | Likely cause |
|---|---|
| Step 7's test URL shows Cloudflare's default "Hello World" text, not JSON/a PDF | The code paste in step 5 didn't fully replace the placeholder, or you deployed before saving the paste. Go back to **Edit code**, confirm the file starts with the matching Worker's opening comment (`// LDT search proxy for...`, `// Test-catalog search proxy for Quest...`, or `// Generic byte-relay proxy for FDA...`), then deploy again. |
| LDT test URL shows `{"error":"Missing required query parameter: q"}` | Working correctly — you forgot to add `?q=GADA` (or similar) to the end of the URL. |
| LDT test URL shows `{"error":"LDT lookup failed", ...}` | The Worker deployed fine but couldn't reach or parse wadsworth.org — check the `detail` field; a timeout usually just means retry, since wadsworth.org can be slow. |
| Quest test URL shows `{"error":"Quest lookup failed", ...}` | The Worker deployed fine but couldn't reach or parse Quest's API — check the `detail` field. If it mentions HTTP 403, Quest may have changed their origin-allowlist behavior; this Worker's whole reason to exist is bypassing that, so a persistent 403 means their API changed and the Worker needs a look. |
| FDA PDF test URL shows `{"error":"No Decision Summary available for this K number",...}` | Working correctly — not every device has one (this is common for older/simpler submissions). Try a different K number. |
| FDA PDF test URL shows `{"error":"Upstream did not return a PDF (possibly rate-limited)...`" | accessdata.fda.gov has aggressive bot detection and occasionally blocks rapid requests — wait a bit and retry. |
| The tool shows "Network error — could not reach the LDT proxy" / "...the Quest proxy" / "Add an FDA PDF proxy Worker URL..." | The URL pasted into Settings is wrong, missing, or empty — re-check it matches exactly what step 7 showed (no trailing `?q=...`/`?k=...`, no trailing slash). |
| Can't find "Create Worker" / only see Pages options | You may be in the **Pages** tab instead of **Workers** — look for a toggle or separate tab between "Workers" and "Pages" near the top of the section. |

## `ldt-proxy.js` — what it does

`GET <worker-url>?q=<term>&status=All|approved|conditionally_approved` →

```json
{
  "term": "CENP-B",
  "total": 1,
  "count": 1,
  "records": [
    {
      "facilityName": "Quest Diagnostics Nichols Institute",
      "facilityId": "...", "projectId": "...", "facilityState": "...",
      "analyte": "...", "method": "...", "specimenType": "...",
      "permitCategory": "...", "status": "Approved",
      "detailLink": "https://www.wadsworth.org/node/.../printable/print"
    }
  ]
}
```

`total` is the true match count reported by the site (accurate even though only the first
50 records are returned — `records` is capped to keep response size/latency predictable,
since a bare 2-3 letter antigen abbreviation can otherwise match thousands of rows).

Notes for anyone modifying this:

- The upstream query always requests the antigen/analyte term as typed by the caller — the
  *client* (not this Worker) is responsible for stripping "Anti-"/Ig-class suffixes before
  calling it, since NY's site defaults to "contains any word" matching and words like "IgG"
  are present in a huge fraction of test names on their own.
- `items_per_page` must be one of the site's actual exposed-filter options (`5`, `10`, `20`,
  `25`, `50`, or `All`) — an arbitrary value like `100` silently breaks the filter server-side
  and the page renders as if nothing matched. This was found the hard way; don't "optimize"
  it back to a round number without re-checking against the real site.

## `quest-proxy.js` — what it does

`GET <worker-url>?q=<term>` →

```json
{
  "term": "Troponin",
  "total": 91,
  "count": 10,
  "records": [
    {
      "testName": "Troponin T, High Sensitivity (hs-TnT)",
      "orderCode": "38685",
      "performingLab": "",
      "aliases": "hs-cTnT, Troponin T, high-sensitivity, Troponin T, hs, Cardiac Troponin T",
      "cptCodes": "84484",
      "status": "Active",
      "id": "MASTER38685"
    }
  ]
}
```

`total` is Quest's own `numFound` (accurate even though `records` only returns what Quest's
API hands back per page — same "don't cap the true count, just the returned list" reasoning as
`ldt-proxy.js`).

Notes for anyone modifying this:

- Unlike NY's site (which simply omits CORS headers), Quest's search API actively 403s any
  request whose `Origin` it doesn't recognize — confirmed live. This Worker works around that
  the same way `ldt-proxy.js` works around NY's missing headers: fetch server-side (Worker-to-
  Quest has no browser-style CORS restriction at all), return the result with this Worker's own
  permissive CORS headers attached.
- The upstream API requires an `x-quest-api-id: test-details-v1` header on every request — a
  request without it is rejected with `{"error":"Missing required header: x-quest-api-id"}`
  before Quest even looks at `q`. This isn't a secret credential, just a required routing
  header their frontend also sends.
- The client (not this Worker) is responsible for narrowing the term to its antigen core and
  whole-word-filtering the results — same division of responsibility as `ldt-proxy.js`, and for
  the same reason: confirmed live, Quest's own search relevance returns real false positives for
  an unrelated test alongside genuine matches, so a literal-text-match filter still has to run
  client-side regardless of which source returned the record.

## `fda-pdf-proxy.js` — what it does

`GET <worker-url>?k=<K number, e.g. K051061>` → the raw bytes of a 510(k) review document PDF
(`Content-Type: application/pdf`), or a JSON error if neither exists (HTTP 404) or something
else went wrong.

FDA's own detail page (`pmn.cfm?ID=...`) labels this document inconsistently across devices —
"Summary", "FDA Review", "Review Summary", "Decision Summary" have all been seen — but that
doesn't matter here, since the Worker goes straight to the known URL patterns rather than
scraping link text. There are two possible documents, and not every device has either one:
the modern "Decision Summary" template (`/cdrh_docs/reviews/{K}.pdf`), tried first, and the
plain clearance-letter-style "Summary" (`/cdrh_docs/pdf{folder}/{K}.pdf`), tried as a fallback
if the first 404s — see `summaryYearFolder()` in the Worker source for how `{folder}` is
derived from the K number's year (it's not simply the zero-padded 2-digit year for every era).

This Worker deliberately does **not** parse the PDF — Cloudflare Workers have no built-in PDF
parser, and bundling one would require a build step this project avoids. It's a pure byte
relay. The tool extracts text from the returned PDF client-side using
[PDF.js](https://mozilla.github.io/pdf.js/) (loaded from a CDN, same pattern as Chart.js/
SheetJS) and looks for the field FDA's standard IVD template uses to state what a device
actually measures — this confirms it more authoritatively than matching against the device
name alone.

Notes for anyone modifying this:

- Not every 510(k) has either document — coverage is good for modern IVD/clinical chemistry
  devices but far weaker (or absent) for older submissions (pre-2000s ones regularly 404 on
  both).
- The plain "Summary" archive's year folder isn't consistently zero-padded — confirmed
  against FDA's own working links: 1996-2001 has no year folder at all (`/cdrh_docs/pdf/`),
  2002-2009 uses a single digit with no leading zero (`/cdrh_docs/pdf7/`, not `pdf07`), and
  2010 onward uses the two-digit year as-is (`/cdrh_docs/pdf25/`). Guessing a zero-padded
  2-digit folder for every record 404s across the entire 1996-2009 range even when a real
  document exists.
- accessdata.fda.gov's bot detection blocks requests without a realistic browser
  `User-Agent` header (returns a small HTML "apology" page instead of the PDF) — the Worker
  already sets one; don't remove it.
- The field is labeled **"Measurand:"** in most documents but **"Analyte:"** in others, and
  the lettered section it falls under varies (seen `B` and `C`, with or without a period after
  the letter — `"C. Measurand:"` vs `"B Measurand:"`). Multi-parameter devices (e.g. hematology
  analyzers) have **no Measurand/Analyte section at all** — confirmed against a real Sysmex
  XN-Series decision summary (K112605), whose section C is "Manufacturer and Instrument Name"
  instead, with the actual parameter list only under "Type of Test or Tests Performed". The
  client-side logic (`MEASURAND_FIELD_LABELS` / `measurandFieldPattern` in the main HTML file)
  tries "Measurand" and "Analyte" first, then falls back to "Type of Test (or Tests
  Performed)" and "Intended Use" for templates with neither — each field's value ends at
  whatever the next lettered section happens to be, rather than assuming a fixed name for it,
  since which section follows which isn't consistent across templates either.
  Matching on the bare word alone caused false negatives (wrong label) and false positives
  (e.g. "measurand" appears as an ordinary metrology term in some precision-study prose, not
  just as a section header — this is why the colon after the label is required, not optional:
  a stray in-sentence mention is never followed directly by a colon). This is reliable for the
  templates seen so far but not guaranteed for every document format FDA has used over the
  decades.
