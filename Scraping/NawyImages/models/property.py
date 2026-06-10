"""
models/property.py
──────────────────
Pure data container for a Nawy property (unit).
No logic — just holds the data fetched from the API.
"""

from dataclasses import dataclass, field


@dataclass
class Property:
    """A single unit / property inside a compound or phase."""
    slug:        str
    images:      list[str] = field(default_factory=list)
    floor_plans: list[str] = field(default_factory=list)
