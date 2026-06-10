from dataclasses import dataclass, field

@dataclass
class Phase:
    slug:       str
    name:       str
    images:     list[str] = field(default_factory=list) # empty list by default
    unit_slugs: list[str] = field(default_factory=list)
    
@dataclass
class Compound:
    slug:       str
    name:       str
    images:     list[str]   = field(default_factory=list)
    phases:     list[Phase] = field(default_factory=list)
    unit_slugs: list[str]   = field(default_factory=list)