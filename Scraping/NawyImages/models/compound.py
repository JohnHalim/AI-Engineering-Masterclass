"""
models/compound.py
──────────────────
Pure data container for a Nawy compound (project).
No logic — just holds the data fetched from the API.
"""

from dataclasses import dataclass, field


@dataclass
class Phase:
    """A phase that lives inside a compound."""
    slug:       str
    name:       str
    images:     list[str] = field(default_factory=list)
    unit_slugs: list[str] = field(default_factory=list)


@dataclass
class Compound:
    """A Nawy compound / project."""
    slug:       str
    name:       str
    images:     list[str]        = field(default_factory=list)
    phases:     list[Phase]      = field(default_factory=list)
    unit_slugs: list[str]        = field(default_factory=list)
