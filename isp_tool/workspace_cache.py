from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from .workspace import ImageWorkItem, RuntimePreviewState


CACHE_HIT = "hit"
CACHE_MISS = "miss"
CACHE_INVALID = "invalid"


@dataclass(frozen=True)
class PreviewCacheContext:
    preview_quality: str
    preview_max_side: int
    backend_cache_key: str
    input_revision: int
    image_identity: int
    pipeline_snapshot: Sequence[dict]


@dataclass(frozen=True)
class CacheLookup:
    status: str
    state: Optional[RuntimePreviewState]


@dataclass(frozen=True)
class CacheSummary:
    count: int
    memory_bytes: int
    max_items: int
    budget_bytes: int

    @property
    def over_budget(self) -> bool:
        return (
            self.count > self.max_items
            or self.memory_bytes > self.budget_bytes
        )


class WorkspacePreviewCachePolicy:
    """UI-independent validity and bounded-LRU policy for work images."""

    def __init__(
        self,
        max_items: int = 3,
        budget_bytes: int = 384 * 1024 * 1024,
    ) -> None:
        self.max_items = max(1, int(max_items))
        self.budget_bytes = max(0, int(budget_bytes))
        self.clock = 0

    @staticmethod
    def entries(
        items: Iterable[ImageWorkItem],
    ) -> List[Tuple[int, ImageWorkItem, RuntimePreviewState]]:
        return [
            (index, item, item.runtime_preview)
            for index, item in enumerate(items)
            if item.runtime_preview is not None
        ]

    def summary(self, items: Iterable[ImageWorkItem]) -> CacheSummary:
        entries = self.entries(items)
        return CacheSummary(
            len(entries),
            sum(max(0, int(state.memory_bytes)) for _, _, state in entries),
            self.max_items,
            self.budget_bytes,
        )

    def touch(self, state: RuntimePreviewState) -> int:
        self.clock = max(self.clock, int(state.last_used)) + 1
        state.last_used = self.clock
        return self.clock

    @staticmethod
    def is_valid(
        state: Optional[RuntimePreviewState],
        context: PreviewCacheContext,
    ) -> bool:
        if state is None:
            return False
        return (
            state.preview_quality == context.preview_quality
            and state.preview_max_side == context.preview_max_side
            and state.backend_cache_key == context.backend_cache_key
            and state.input_revision == context.input_revision
            and state.image_identity == context.image_identity
            and state.pipeline_snapshot == context.pipeline_snapshot
            and bool(state.results)
            and state.pipeline_cache.get("results") is not None
        )

    def lookup(
        self,
        item: ImageWorkItem,
        context: PreviewCacheContext,
    ) -> CacheLookup:
        state = item.runtime_preview
        if state is None:
            return CacheLookup(CACHE_MISS, None)
        if not self.is_valid(state, context):
            item.runtime_preview = None
            return CacheLookup(CACHE_INVALID, None)
        self.touch(state)
        return CacheLookup(CACHE_HIT, state)

    def put(
        self,
        item: ImageWorkItem,
        state: RuntimePreviewState,
        items: Iterable[ImageWorkItem],
        *,
        protected_item: Optional[ImageWorkItem] = None,
    ) -> List[ImageWorkItem]:
        self.touch(state)
        item.runtime_preview = state
        return self.trim(
            items,
            protected_item=(protected_item or item),
        )

    def trim(
        self,
        items: Iterable[ImageWorkItem],
        *,
        protected_item: Optional[ImageWorkItem] = None,
    ) -> List[ImageWorkItem]:
        item_list = list(items)
        evicted: List[ImageWorkItem] = []
        while self.summary(item_list).over_budget:
            candidates = [
                (index, item, state)
                for index, item, state in self.entries(item_list)
                if item is not protected_item
            ]
            if not candidates:
                break
            _index, victim, _state = min(
                candidates,
                key=lambda entry: (entry[2].last_used, entry[0]),
            )
            victim.runtime_preview = None
            evicted.append(victim)
        return evicted

    @staticmethod
    def clear(items: Iterable[ImageWorkItem]) -> int:
        count = 0
        for item in items:
            if item.runtime_preview is not None:
                item.runtime_preview = None
                count += 1
        return count
