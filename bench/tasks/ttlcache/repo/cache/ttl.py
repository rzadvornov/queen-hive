"""A small in-memory cache with expiry and a size limit."""

import time
from typing import Callable, Hashable


class TTLCache:
    """Cache with per-entry time to live and least-recently-used eviction.

    - TTLCache(max_size, ttl, clock=time.monotonic): max_size >= 1 entries, ttl > 0 seconds;
      invalid values raise ValueError. `clock` returns the current time in seconds.
    - put(key, value): store or replace; the entry expires `ttl` seconds after this put.
      When a new key would exceed max_size, the least recently used live entry is evicted
      (expired entries are dropped first).
    - get(key, default=None): the value if present and not expired, else default.
      A successful get makes the entry the most recently used. It does not extend its expiry.
    - len(cache): the number of live (not expired) entries.
    - `key in cache`: True for a live entry; does not count as a use.
    - clear(): remove everything.
    """

    def __init__(self, max_size: int, ttl: float, clock: Callable[[], float] = time.monotonic):
        raise NotImplementedError

    def put(self, key: Hashable, value) -> None:
        raise NotImplementedError

    def get(self, key: Hashable, default=None):
        raise NotImplementedError
