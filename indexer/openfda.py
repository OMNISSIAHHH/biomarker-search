"""openFDA HTTP client: the 510(k) endpoint, with the same retry/backoff behavior
as fetchOpenFdaWithRetry/runOpenFdaQuery in FDA510kBiomarkerSearch.html
(exponential backoff on 429s and network errors, 3 retries, 100-record pages,
300-record cap per query) so results stay consistent with the live JS tool.
"""
import asyncio

import httpx

MAX_FETCH_RETRIES = 3
PAGE_LIMIT = 100
MAX_RECORDS = 300

DEVICE_510K = "https://api.fda.gov/device/510k.json"
DEVICE_PMA = "https://api.fda.gov/device/pma.json"


class OpenFdaError(Exception):
    pass


async def fetch_with_retry(client: httpx.AsyncClient, url: str, params: dict) -> httpx.Response:
    for attempt in range(MAX_FETCH_RETRIES + 1):
        try:
            res = await client.get(url, params=params, timeout=30.0)
        except httpx.HTTPError:
            if attempt >= MAX_FETCH_RETRIES:
                raise OpenFdaError(
                    "Network error - could not reach the openFDA API. Check your connection and try again."
                )
            await asyncio.sleep(0.5 * 2 ** attempt)
            continue
        if res.status_code == 429:
            if attempt >= MAX_FETCH_RETRIES:
                raise OpenFdaError(
                    f"Rate limit exceeded on the openFDA API after {MAX_FETCH_RETRIES} retries."
                )
            await asyncio.sleep(1.0 * 2 ** attempt)
            continue
        return res
    raise OpenFdaError("unreachable")  # pragma: no cover


async def run_query(client: httpx.AsyncClient, endpoint: str, expr: str, api_key: str | None = None,
                     max_records: int | None = MAX_RECORDS) -> dict:
    """Mirrors runOpenFdaQuery: paginate skip/limit up to max_records, return {total, records}.
    max_records=None paginates through the entire result set with no cap — used by
    fetch_all_in_scope below, where the whole point is reaching every device in scope, not a
    capped sample of it. Defaults to MAX_RECORDS (300), matching the live browser tool's
    documented per-search display cap, for every other caller (the confirmed-match tiers in
    indexer/matching.py) where that cap is intentional.
    """
    records: list[dict] = []
    total = 0
    skip = 0
    while True:
        params = {"search": expr, "limit": PAGE_LIMIT, "skip": skip}
        if api_key:
            params["api_key"] = api_key
        res = await fetch_with_retry(client, endpoint, params)
        if res.status_code == 404:
            total = 0
            break
        if res.status_code >= 400:
            try:
                body = res.json()
                msg = body.get("error", {}).get("message") or f"HTTP {res.status_code}"
            except Exception:
                msg = f"HTTP {res.status_code}"
            raise OpenFdaError(msg)
        data = res.json()
        records.extend(data.get("results", []))
        total = data.get("meta", {}).get("results", {}).get("total", 0)
        skip += PAGE_LIMIT
        if not (skip < total and (max_records is None or skip < max_records)):
            break
    return {"total": total, "records": records}


async def fetch_all_in_scope(client: httpx.AsyncClient, endpoint: str, committee_field: str,
                              committees: list[str], api_key: str | None = None) -> list[dict]:
    """Fetch every record in `endpoint` whose committee_field is one of `committees` — the
    bounded crawl scope. Uncapped (max_records=None) per committee: this previously reused
    run_query's default 300-record cap, silently truncating every committee's population to the
    same 300 devices regardless of how many actually exist — confirmed live, exactly 6
    committees x 300 = 1800 devices in scope, every single crawl run, no matter how much of
    FDA's real history each panel actually has. The predicate graph's whole value is reaching
    devices text search misses entirely, so it needs the true full population per committee, not
    a capped sample of it — unlike a live per-biomarker search, where 300 is an intentional,
    documented "don't take forever" limit (see run_query).

    One query per committee (rather than one giant OR) keeps partial-failure retry simple (a
    single committee's fetch can be retried without redoing the others) — deliberately load-
    bearing now that a committee's full history can be 10,000+ records deep: confirmed live,
    openFDA occasionally returns a generic 400 ("Check your request and try again") on some page
    of a long paginated fetch, not reproducible against a fixed skip/limit in isolation, so it
    reads as an intermittent upstream hiccup rather than a deterministic bug tied to one value.
    A single committee hitting this shouldn't lose the other five, so it's caught and skipped
    here (with whatever it already found up to that point) rather than crashing the whole run —
    re-run with `--committees <the skipped one(s)>` to retry just those.
    """
    seen: dict[str, dict] = {}
    for committee in committees:
        expr = f'{committee_field}:"{committee}"'
        try:
            result = await run_query(client, endpoint, expr, api_key, max_records=None)
        except OpenFdaError as e:
            print(f"  {committee}: fetch failed ({e}) — skipping this committee for now, "
                  f"re-run with --committees {committee} to retry it")
            continue
        for r in result["records"]:
            k = r.get("k_number")
            if k:
                seen[k] = r
    return list(seen.values())
