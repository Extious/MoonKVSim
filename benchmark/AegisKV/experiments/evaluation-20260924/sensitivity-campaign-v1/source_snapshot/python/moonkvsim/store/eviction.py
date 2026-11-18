"""Source-aligned vanilla Mooncake eviction-key ordering."""

from __future__ import annotations

from collections import deque


class LRUEvictionStrategy:
    """Front is most recent; eviction removes the least-recent tail."""

    def __init__(self) -> None:
        self._keys: deque[str] = deque()
        self._members: set[str] = set()

    def __len__(self) -> int:
        return len(self._keys)

    @property
    def keys_mru_to_lru(self) -> tuple[str, ...]:
        return tuple(self._keys)

    @property
    def keys_lru_to_mru(self) -> tuple[str, ...]:
        """Return a non-mutating, deterministic capacity-pressure scan order."""

        return tuple(reversed(self._keys))

    def add_key(self, key: str) -> None:
        if not key:
            raise ValueError("eviction key must be non-empty")
        if key in self._members:
            self._keys.remove(key)
        else:
            self._members.add(key)
        self._keys.appendleft(key)

    def update_key(self, key: str) -> None:
        if key in self._members:
            self._keys.remove(key)
            self._keys.appendleft(key)

    def remove_key(self, key: str) -> bool:
        if key not in self._members:
            return False
        self._members.remove(key)
        self._keys.remove(key)
        return True

    def evict_key(self) -> str | None:
        if not self._keys:
            return None
        key = self._keys.pop()
        self._members.remove(key)
        return key

    def clean_up(self) -> None:
        self._keys.clear()
        self._members.clear()

    def audit(self) -> None:
        if len(self._keys) != len(self._members) or set(self._keys) != self._members:
            raise RuntimeError("LRU list/index invariant failed")


class FIFOEvictionStrategy:
    """Pinned FIFO semantics: adds may duplicate and random removal is a no-op."""

    def __init__(self) -> None:
        self._keys: deque[str] = deque()

    def __len__(self) -> int:
        return len(self._keys)

    def add_key(self, key: str) -> None:
        if not key:
            raise ValueError("eviction key must be non-empty")
        self._keys.appendleft(key)

    def update_key(self, key: str) -> None:
        del key

    def remove_key(self, key: str) -> bool:
        # Pinned Mooncake's FIFO AddKey deliberately does not populate the
        # base-class key index, so the inherited RemoveKey returns OK without
        # deleting a queue entry.  ``False`` means no local entry changed.
        del key
        return False

    def evict_key(self) -> str | None:
        return self._keys.pop() if self._keys else None

    def clean_up(self) -> None:
        self._keys.clear()
