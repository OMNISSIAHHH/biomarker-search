// Test-catalog search proxy for Quest Diagnostics' public Test Directory.
//
// testdirectory.questdiagnostics.com's search API actively rejects cross-origin requests
// (a 403, not just a missing CORS header — confirmed live: it allowlists only its own origin),
// so a browser can't call it directly. This Worker fetches it server-side (no CORS restriction
// between servers, and it already runs from a real IP the API accepts) and returns clean JSON
// with CORS enabled, same pattern as ldt-proxy.js for NY's site.
//
// Deploy: paste this file's contents into a new Worker in the Cloudflare dashboard
// (Workers & Pages -> Create -> Create Worker -> edit code -> paste -> Deploy).
// No local Node/wrangler needed. Then set the deployed Worker's URL as the Quest proxy Worker
// URL in FDA510kBiomarkerSearch.html's Settings panel.

const UPSTREAM_URL = 'https://testdirectory.questdiagnostics.com/test/search';
const MAX_RECORDS = 50; // bound response size, same reasoning as ldt-proxy.js's own cap

function corsHeaders() {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', ...corsHeaders() },
  });
}

function cleanText(s) {
  return (s || '').replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
}

async function searchQuest(term) {
  const upstream = new URL(UPSTREAM_URL);
  upstream.searchParams.set('q', term);

  const res = await fetch(upstream.toString(), {
    headers: {
      // Required by the upstream API — confirmed live, a request without this header is
      // rejected with "Missing required header: x-quest-api-id" before it even looks at `q`.
      'x-quest-api-id': 'test-details-v1',
      'Accept': 'application/json',
      'User-Agent': 'Mozilla/5.0 (compatible; QuestLookupProxy/1.0; +biomarker search tool)',
    },
  });
  if (!res.ok) {
    throw new Error(`Upstream returned HTTP ${res.status}`);
  }
  const data = await res.json();
  const docs = (data && data.response && data.response.docs) || [];

  const records = docs.slice(0, MAX_RECORDS).map((d) => ({
    testName: cleanText(d.title || d.TestName || ''),
    orderCode: cleanText(d.OrderCode || d.NTC || ''),
    performingLab: cleanText(d.PerformingLab || ''),
    aliases: cleanText(Array.isArray(d.Aliases) ? d.Aliases.join(', ') : (d.Aliases || '')),
    cptCodes: cleanText(Array.isArray(d.CPTCodes) ? d.CPTCodes.join(', ') : (d.CPTCodes || '')),
    status: cleanText(d.TestStatus || ''),
    id: cleanText(d.id || ''),
  }));

  const total = (data && data.response && data.response.numFound) || records.length;
  return { total, records };
}

export default {
  async fetch(request) {
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders() });
    }

    const url = new URL(request.url);
    const term = (url.searchParams.get('q') || '').trim();

    if (!term) {
      return json({ error: 'Missing required query parameter: q' }, 400);
    }

    try {
      const { total, records } = await searchQuest(term);
      return json({ term, total, count: records.length, records });
    } catch (err) {
      return json({ error: 'Quest lookup failed', detail: String(err && err.message || err) }, 502);
    }
  },
};
