"""Buffer backend registry.

Class-level plugin registry: add a new storage backend (Drive/OneDrive/S3/
Nextcloud, ...) by subclassing BufferBackend and registering it under a
name, without touching tools.py or server.py.

    @BufferRegistry.register("local")
    class LocalFileBackend(BufferBackend):
        ...

    backend = BufferRegistry.get_backend("local")
"""

from __future__ import annotations

from typing import Callable, Dict, Type

from .backend import BufferBackend


class BufferRegistry:
    """Registers BufferBackend subclasses by name and hands out instances."""

    _classes: Dict[str, Type[BufferBackend]] = {}
    _instances: Dict[str, BufferBackend] = {}

    @classmethod
    def register(cls, name: str) -> Callable[[Type[BufferBackend]], Type[BufferBackend]]:
        """Decorator: register a BufferBackend subclass under `name`."""

        def decorator(backend_cls: Type[BufferBackend]) -> Type[BufferBackend]:
            cls._classes[name] = backend_cls
            return backend_cls

        return decorator

    @classmethod
    def get_backend(cls, name: str, **kwargs) -> BufferBackend:
        """Return a cached instance of the backend registered as `name`.

        Extra kwargs are only used the first time a given name is
        instantiated; later calls return the cached instance regardless.

        Raises:
            ValueError: If `name` was never registered.
        """
        if name in cls._instances:
            return cls._instances[name]
        backend_cls = cls._classes.get(name)
        if backend_cls is None:
            known = ", ".join(sorted(cls._classes)) or "(none registered)"
            raise ValueError(f"Unknown buffer backend '{name}'. Known backends: {known}")
        instance = backend_cls(**kwargs)
        cls._instances[name] = instance
        return instance

    @classmethod
    def known_backends(cls) -> list[str]:
        return sorted(cls._classes)

    @classmethod
    def _reset_for_tests(cls) -> None:
        """Test-only: clear cached instances so a fresh one is built next call."""
        cls._instances.clear()
