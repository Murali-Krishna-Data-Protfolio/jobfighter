"""
SOURCE_REGISTRY — maps a source_type string ("adzuna", "jsearch", ...) to
its JobSource class. A new source is one new file plus one decorator line
here (or a direct import + register call); nothing else in the codebase
needs to know it exists ahead of time.
"""

from __future__ import annotations

from typing import Type

from packages.sources.base import JobSource

SOURCE_REGISTRY: dict[str, Type[JobSource]] = {}


def register_source(source_type: str):
    def _decorator(cls: Type[JobSource]) -> Type[JobSource]:
        cls.source_type = source_type
        SOURCE_REGISTRY[source_type] = cls
        return cls
    return _decorator


def get_source_class(source_type: str) -> Type[JobSource]:
    try:
        return SOURCE_REGISTRY[source_type]
    except KeyError:
        raise ValueError(
            f"Unknown source_type {source_type!r}. Registered: {sorted(SOURCE_REGISTRY)}"
        ) from None
