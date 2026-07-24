// Generic byte-relay proxy for FDA 510(k) review documents.
//
// accessdata.fda.gov sends no Access-Control-Allow-Origin header, so a browser blocks any
// client-side fetch() from reading a PDF hosted there — same problem as the LDT database
// (see ldt-proxy.js). This Worker just fetches the PDF server-side and relays the raw bytes
// with CORS enabled; it does NOT parse the PDF itself (Cloudflare Workers have no built-in
// PDF parser, and bundling one would require a build step this project intentionally
// avoids). Text extraction (looking for the "Measurand:"/"Analyte:" field) happens
// client-side using PDF.js, loaded from a CDN just like Chart.js/SheetJS already are.
//
// FDA's own detail page (pmn.cfm?ID=...) labels the review document inconsistently across
// devices — "Summary", "FDA Review", "Review Summary", "Decision Summary" have all been seen
// — but the label doesn't matter here since we go straight to the known URL patterns rather
// than scraping the link text. There are two possible documents, and not every device has
// either one:
//   - the modern "Decision Summary" template, at /cdrh_docs/reviews/{K}.pdf
//   - the plain clearance-letter-style "Summary", at /cdrh_docs/pdf{folder}/{K}.pdf — see
//     summaryYearFolder() below for how {folder} is derived from the K number's year; it is
//     NOT simply the zero-padded 2-digit year for every record.
// Some devices have both, some have only one, some (mostly pre-2000s) have neither. Try the
// Decision Summary first (it's the one with a reliable "Measurand:"/"Analyte:" field), fall
// back to the plain Summary if that 404s.
//
// Deploy exactly like ldt-proxy.js — paste into a new Cloudflare Worker via the dashboard,
// no local Node/wrangler needed. See worker/README.md.

const DECISION_SUMMARY_BASE = 'https://www.accessdata.fda.gov/cdrh_docs/reviews';
const SUMMARY_BASE = 'https://www.accessdata.fda.gov/cdrh_docs';
const BROWSER_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36';

// FDA's plain "Summary" archive isn't consistently zero-padded by year. Confirmed against
// FDA's own working links for real K numbers spanning every era:
//   - 1996-2001 (K-number year code 96-99, 00-01): no year folder at all -> /cdrh_docs/pdf/
//   - 2002-2009 (code 02-09): single digit, NOT zero-padded -> /cdrh_docs/pdf7/, not pdf07/
//   - 2010 onward (code 10-99): the two-digit code as-is -> /cdrh_docs/pdf25/
// Always zero-padding to 2 digits (e.g. building "pdf07") 404s for the whole 2002-2009 range
// and for 1996-2001, silently hiding real, existing documents. Both K-numbers (K123456) and
// De Novo numbers (DEN123456, see DEVICE_NUMBER_RE below) encode this 2-digit year right
// after their letter prefix — just at a different offset, since "DEN" is 3 characters where
// "K" is 1 (confirmed via curl: DEN140001's year folder is "pdf14", same rule as a K-number).
function summaryYearFolder(deviceNumber) {
  const yearStart = deviceNumber.startsWith('DEN') ? 3 : 1;
  const yy = parseInt(deviceNumber.slice(yearStart, yearStart + 2), 10);
  if (yy >= 96 || yy <= 1) return '';
  return String(yy); // no leading zero for 2-9; "10"-"99" already print as-is
}

// openFDA's 510k dataset also includes De Novo classification grants (k_number like
// DEN140001) alongside real 510(k)s (K123456) — see the same distinction made for the detail
// link in FDA510kBiomarkerSearch.html's detailUrlFor(). Confirmed via curl that De Novo
// devices have review documents at the exact same URL patterns as K-numbers (both
// /cdrh_docs/reviews/{number}.pdf and the /cdrh_docs/pdf{folder}/ fallback), so no other
// change is needed here beyond accepting the format.
const DEVICE_NUMBER_RE = /^(K\d{6}|DEN\d{6})$/;

function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };
}

function jsonError(obj, status) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', ...corsHeaders() },
  });
}

// accessdata.fda.gov's bot detection blocks requests without a browser-like UA (returns a
// small "apology" HTML page instead of the real file), so every fetch needs it.
function fetchUpstream(url) {
  return fetch(url, { headers: { 'User-Agent': BROWSER_UA } });
}

export default {
  async fetch(request) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders() });
    }

    const url = new URL(request.url);
    const kNumber = (url.searchParams.get('k') || '').trim().toUpperCase();

    if (!DEVICE_NUMBER_RE.test(kNumber)) {
      return jsonError({ error: 'Missing or malformed required query parameter: k (expected like K123456 or DEN123456)' }, 400);
    }

    let res;
    let source = 'decision-summary';
    try {
      res = await fetchUpstream(`${DECISION_SUMMARY_BASE}/${kNumber}.pdf`);
      if (res.status === 404) {
        source = 'summary';
        res = await fetchUpstream(`${SUMMARY_BASE}/pdf${summaryYearFolder(kNumber)}/${kNumber}.pdf`);
      }
    } catch (err) {
      return jsonError({ error: 'Upstream fetch failed', detail: String(err && err.message || err) }, 502);
    }

    if (res.status === 404) {
      return jsonError({ error: 'No Decision Summary or Summary document available for this K number', kNumber }, 404);
    }
    if (!res.ok) {
      return jsonError({ error: `Upstream returned HTTP ${res.status}`, kNumber }, 502);
    }

    const contentType = res.headers.get('content-type') || '';
    if (!contentType.includes('pdf')) {
      // Likely the bot-detection "apology" page rather than a real PDF.
      return jsonError({ error: 'Upstream did not return a PDF (possibly rate-limited) — try again shortly', kNumber }, 502);
    }

    return new Response(res.body, {
      status: 200,
      headers: { 'Content-Type': 'application/pdf', 'X-Document-Source': source, ...corsHeaders() },
    });
  },
};
