"""Propagates confirmed biomarker matches across the predicate citation graph: if device D
cites predicate P, and P is already a confirmed match for biomarker B, mark D as an inferred
match for B (via_k_number = P — the actual predicate D cites, so a human can go verify it
directly, not some distant ancestor several hops back).

Capped at MAX_HOPS: a predicate citation doesn't always mean "measures the same analyte" —
sometimes it's cited for instrument/methodology equivalence only. The further removed a
citation is from a confirmed device, the weaker that assumption gets, so this stays shallow
rather than propagating indefinitely through the whole graph.
"""
import time

from indexer import db

MAX_HOPS = 3


def _trace(trace: list[dict] | None, stage: str, outcome: str, detail: str,
           elapsed_ms: int | None = None) -> None:
    """See indexer/ai_expansion.py's identical helper — a no-op when trace is None."""
    if trace is not None:
        trace.append({"stage": stage, "outcome": outcome, "detail": detail, "elapsedMs": elapsed_ms})


def propagate_predicate_matches(conn, biomarker_key: str, trace: list[dict] | None = None) -> int:
    t0 = time.monotonic()
    confirmed = {
        row["k_number"]
        for row in conn.execute(
            "SELECT DISTINCT k_number FROM biomarker_matches WHERE biomarker_key = ? AND confidence = 'confirmed'",
            (biomarker_key,),
        )
    }
    if not confirmed:
        _trace(trace, "predicate-propagation", "miss", "no confirmed matches to propagate from",
               int((time.monotonic() - t0) * 1000))
        return 0

    citing: dict[str, list[str]] = {}
    for row in conn.execute("SELECT device_k, predicate_k FROM predicates"):
        citing.setdefault(row["predicate_k"], []).append(row["device_k"])

    added = 0
    frontier = set(confirmed)
    already_matched = set(confirmed)
    for _hop in range(MAX_HOPS):
        next_frontier: set[str] = set()
        for predicate_k in frontier:
            for device_k in citing.get(predicate_k, []):
                if device_k in already_matched:
                    continue
                db.insert_match(conn, device_k, biomarker_key, "predicate", "inferred", via_k_number=predicate_k)
                already_matched.add(device_k)
                next_frontier.add(device_k)
                added += 1
        if not next_frontier:
            break
        frontier = next_frontier

    elapsed = int((time.monotonic() - t0) * 1000)
    if added > 0:
        _trace(trace, "predicate-propagation", "hit",
               f"{added} inferred match(es) added via predicate citation, up to {MAX_HOPS} hop(s)", elapsed)
    else:
        _trace(trace, "predicate-propagation", "miss",
               "had confirmed match(es), but nothing cites them as a predicate", elapsed)
    return added
