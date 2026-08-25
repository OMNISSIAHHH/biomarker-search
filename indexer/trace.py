"""TraceSink: a list-like sink whose .append() also notifies a callback the instant each entry
is added. Every _trace(trace, ...) call site across ai_expansion.py/matching.py/predicate_graph.py
just does trace.append(...) — passing a TraceSink instead of a plain list makes those same call
sites stream live over SSE (see server/main.py's GET /biomarker/{term}/stream) with zero changes
to any of them, while .entries still behaves as the plain final trace array non-streaming callers
(compute_and_cache_result's own return value) already expect.
"""


class TraceSink:
    def __init__(self, on_entry=None):
        self.entries: list[dict] = []
        self._on_entry = on_entry

    def append(self, entry: dict) -> None:
        self.entries.append(entry)
        if self._on_entry:
            self._on_entry(entry)
