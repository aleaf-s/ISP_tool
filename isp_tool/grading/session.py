"""Per-image editing state, separate from the shared catalogue UI."""
from dataclasses import dataclass, field
from .model import GradeHistory, ColorPoint, build_lut
from functools import lru_cache
from .hsv_grid import HSVState
from .ca import CAState


@lru_cache(maxsize=4)
def preview_lut(key):
    """Small shared LUT cache, populated by the fast-preview worker."""
    return build_lut([ColorPoint(*entry) for entry in key])


def processing_key(points):
    # Labels, ownership and selection are not colour-processing parameters.
    return tuple((tuple(p.source), tuple(p.target), p.radius, p.strength, p.enabled)
                 for p in points)


@dataclass
class GradingState:
    history: GradeHistory = field(default_factory=GradeHistory)
    selected_id: str = ''
    drafts: dict = field(default_factory=dict)
    enabled: bool = True
    cache_key: object = None
    output: object = None
    method: str = '取色调色'
    # Internal name retained for shared rendering code; UI exposes HSV only.
    clut: HSVState = field(default_factory=HSVState)
    ca: CAState = field(default_factory=CAState)
