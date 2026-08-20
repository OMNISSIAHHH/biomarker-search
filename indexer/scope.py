"""Crawl boundary: advisory committees already relevant to the biomarker dictionary,
reused from the same list the existing HTML tool's "Rule out FDA review panel" filter
surfaces in practice for this tool's IVD-heavy dictionary — not all of FDA's ~30
committees. Keeps the crawl to a few thousand devices instead of FDA's full history.
"""

ADVISORY_COMMITTEES = [
    "IM",  # Immunology
    "CH",  # Clinical Chemistry
    "HE",  # Hematology
    "MI",  # Microbiology
    "PA",  # Pathology
    "TX",  # Toxicology
]
