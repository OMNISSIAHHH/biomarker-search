"""Propagates confirmed biomarker matches across the predicate citation graph: if device D
cites predicate P, and P is already a confirmed match for biomarker B, mark D as an inferred
match for B (via_k_number = P — the actual predicate D cites, so a human can go verify it
directly, not some distant ancestor several hops back).

Capped at MAX_HOPS: a predicate citation doesn't always mean "measures the same analyte" —
sometimes it's cited for instrument/methodology equivalence only. The further removed a
citation is from a confirmed device, the weaker that assumption gets, so this stays shallow
rather than propagating indefinitely through the whole graph.
"""
from indexer import db

MAX_HOPS = 3


def propagate_predicate_matches(conn, biomarker_key: str) -> int:
    confirmed = {
        row["k_number"]
        for row in conn.execute(
            "SELECT DISTINCT k_number FROM biomarker_matches WHERE biomarker_key = ? AND confidence = 'confirmed'",
            (biomarker_key,),
        )
    }
    if not confirmed:
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
    return added
