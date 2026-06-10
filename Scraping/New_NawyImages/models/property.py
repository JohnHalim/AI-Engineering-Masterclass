from dataclasses import dataclass, field

@dataclass
class Property:
    slug:        str
    images:      list[str] = field(default_factory=list)
    floor_plans: list[str] = field(default_factory=list)