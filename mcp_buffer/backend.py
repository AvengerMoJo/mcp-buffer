"""Abstract buffer backend interface.

Every backend (local filesystem today; Google Drive/OneDrive/S3/Nextcloud
as future plugins) implements this same contract so tools.py and any
caller never needs to know which one is active.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Union

from .models import BufferEntry


class BufferBackendError(Exception):
    """Base exception for buffer backend errors."""


class BufferBackend(ABC):
    """Abstract base class for buffer backends."""

    @abstractmethod
    async def buffer_upload(
        self,
        content: Union[str, bytes],
        filename: str,
        mime_type: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        folder_id: Optional[str] = None,
    ) -> BufferEntry:
        """Store a file and return its BufferEntry.

        Args:
            content: A local filesystem path to copy in, or raw bytes.
            filename: Name to store/serve the file as.
            mime_type: Content-Type; guessed from filename if omitted.
            ttl_seconds: Optional expiry, relative to now.
            folder_id: Optional backend-specific grouping key.

        Raises:
            BufferBackendError: If the upload fails.
        """

    @abstractmethod
    async def get_link(self, buffer_id: str) -> str:
        """Return a URL a consumer can GET/stream the file from.

        Raises:
            BufferBackendError: If buffer_id is unknown or expired.
        """

    @abstractmethod
    async def expire(self, buffer_id: str) -> None:
        """Mark an entry expired and release its storage.

        Raises:
            BufferBackendError: If buffer_id is unknown.
        """

    @abstractmethod
    async def list(self, folder_id: Optional[str] = None) -> list[BufferEntry]:
        """List active entries, newest first, optionally filtered by folder_id."""

    @abstractmethod
    async def can_reuse(self, buffer_id: str) -> bool:
        """True if buffer_id still exists and has not expired."""
