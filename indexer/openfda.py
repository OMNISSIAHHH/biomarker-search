"""openFDA HTTP client: 510(k) and PMA endpoints, with the same retry/backoff
behavior as fetchOpenFdaWithRetry/runOpenFdaQuery in FDA510kBiomarkerSearch.html
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


async def run_query(client: httpx.AsyncClient, endpoint: str, expr: str, api_key: str | None = None) -> dict:
    """Mirrors runOpenFdaQuery: paginate skip/limit up to MAX_RECORDS, return {total, records}."""
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
        if not (skip < total and skip < MAX_RECORDS):
            break
    return {"total": total, "records": records}


async def fetch_all_in_scope(client: httpx.AsyncClient, endpoint: str, committee_field: str,
                              committees: list[str], api_key: str | None = None) -> list[dict]:
    """Fetch every record in `endpoint` whose committee_field is one of `committees` — the
    bounded crawl scope. One query per committee (rather than one giant OR) keeps each
    individual query's result count well under MAX_RECORDS pagination surprises and makes
    partial-failure retry simpler (a single committee's fetch can be retried without redoing
    the others).
    """
    seen: dict[str, dict] = {}
    for committee in committees:
        expr = f'{committee_field}:"{committee}"'
        result = await run_query(client, endpoint, expr, api_key)
        for r in result["records"]:
            k = r.get("k_number") or r.get("pma_number")
            if k:
                seen[k] = r
    return list(seen.values())
