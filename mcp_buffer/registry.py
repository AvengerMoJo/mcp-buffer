"""Buffer registry for managing multiple backend instances."""

from typing import Optional

from .backend import BufferBackend
from .models import BufferEntry


class BufferRegistry:
    """Registry for buffer backends.

    Manages multiple backend instances and provides a unified interface
    for buffer operations. Supports failover between backends if configured.
    """

    def __init__(self, primary_backend: Optional[BufferBackend] = None):
        """Initialize the registry with an optional primary backend.

        Args:
            primary_backend: The primary backend to use for operations.
        """
        self._primary_backend: Optional[BufferBackend] = primary_backend
        self._backends: list[BufferBackend] = []
        if primary_backend is not None:
            self._backends.append(primary_backend)

    def register_backend(self, backend: BufferBackend) -> None:
        """Register a backup backend.

        Args:
            backend: The backend to register as a backup option.
        """
        self._backends.append(backend)

    @property
    def primary_backend(self) -> Optional[BufferBackend]:
        """Get the primary backend."""
        return self._primary_backend

    async def create_entry(self, entry: BufferEntry) -> BufferEntry:
        """Create a new buffer entry using the primary backend.

        Args:
            entry: The buffer entry to create.

        Returns:
            The created entry.

        Raises:
            RuntimeError: If no primary backend is configured.
            BufferBackendError: If creation fails.
        """
        if self._primary_backend is None:
            raise RuntimeError("No primary backend configured")
        return await self._primary_backend.create_entry(entry)

    async def get_entry(self, entry_id: str) -> Optional[BufferEntry]:
        """Retrieve a buffer entry by ID using the primary backend.

        Args:
            entry_id: The unique identifier of the entry.

        Returns:
            The requested entry, or None if not found.

        Raises:
            RuntimeError: If no primary backend is configured.
            BufferBackendError: If retrieval fails for non-technical reasons.
        """
        if self._primary_backend is None:
            raise RuntimeError("No primary backend configured")
        return await self._primary_backend.get_entry(entry_id)

    async def update_entry(self, entry: BufferEntry) -> BufferEntry:
        """Update an existing buffer entry using the primary backend.

        Args:
            entry: The buffer entry with updated content.

        Returns:
            The updated entry.

        Raises:
            RuntimeError: If no primary backend is configured.
            BufferBackendError: If the entry doesn't exist or update fails.
        """
        if self._primary_backend is None:
            raise RuntimeError("No primary backend configured")
        return await self._primary_backend.update_entry(entry)

    async def delete_entry(self, entry_id: str) -> bool:
        """Delete a buffer entry by ID using the primary backend.

        Args:
            entry_id: The unique identifier of the entry to delete.

        Returns:
            True if deleted, False if not found.

        Raises:
            RuntimeError: If no primary backend is configured.
            BufferBackendError: If deletion fails for non-technical reasons.
        """
        if self._primary_backend is None:
            raise RuntimeError("No primary backend configured")
        return await self._primary_backend.delete_entry(entry_id)

    async def list_entries(self) -> list[BufferEntry]:
        """List all buffer entries using the primary backend.

        Returns:
            A list of all buffer entries, ordered by creation time (newest first).

        Raises:
            RuntimeError: If no primary backend is configured.
            BufferBackendError: If listing fails for non-technical reasons.
        """
        if self._primary_backend is None:
            raise RuntimeError("No primary backend configured")
        return await self._primary_backend.list_entries()
