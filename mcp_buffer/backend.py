"""Abstract buffer backend interface."""

from abc import ABC, abstractmethod
from typing import Optional

from .models import BufferEntry


class BufferBackendError(Exception):
    """Base exception for buffer backend errors."""

    pass


class BufferBackend(ABC):
    """Abstract base class for buffer backends.

    Subclasses must implement all methods to provide concrete storage mechanisms.
    """

    @abstractmethod
    async def create_entry(self, entry: BufferEntry) -> BufferEntry:
        """Create a new buffer entry.

        Args:
            entry: The buffer entry to create.

        Returns:
            The created entry with updated fields if applicable.

        Raises:
            BufferBackendError: If creation fails.
        """
        pass

    @abstractmethod
    async def get_entry(self, entry_id: str) -> Optional[BufferEntry]:
        """Retrieve a buffer entry by ID.

        Args:
            entry_id: The unique identifier of the entry.

        Returns:
            The requested entry, or None if not found.

        Raises:
            BufferBackendError: If retrieval fails for non-technical reasons.
        """
        pass

    @abstractmethod
    async def update_entry(self, entry: BufferEntry) -> BufferEntry:
        """Update an existing buffer entry.

        Args:
            entry: The buffer entry with updated content.

        Returns:
            The updated entry.

        Raises:
            BufferBackendError: If the entry doesn't exist or update fails.
        """
        pass

    @abstractmethod
    async def delete_entry(self, entry_id: str) -> bool:
        """Delete a buffer entry by ID.

        Args:
            entry_id: The unique identifier of the entry to delete.

        Returns:
            True if deleted, False if not found.

        Raises:
            BufferBackendError: If deletion fails for non-technical reasons.
        """
        pass

    @abstractmethod
    async def list_entries(self) -> list[BufferEntry]:
        """List all buffer entries.

        Returns:
            A list of all buffer entries, ordered by creation time (newest first).

        Raises:
            BufferBackendError: If listing fails for non-technical reasons.
        """
        pass
