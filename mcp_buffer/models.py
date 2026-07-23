"""Data models for mcp-buffer.

A buffer entry represents one *file* -- bytes on disk, or bytes destined
for a remote object store -- not a row of text. The point of this package
is letting an MCP agent hand off a file it can't process locally (a large
PDF, a .docx) to a backend that can, via a link/stream rather than a JSON-
RPC payload. See backend.py for the provider contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


class BufferEntry(BaseModel):
    """Metadata for one buffered file."""

    buffer_id: str = Field(..., description="Unique identifier for this entry")
    provider: str = Field(..., description="Backend that stores this entry, e.g. 'local'")
    filename: str = Field(..., description="Original filename")
    mime_type: str = Field(..., description="Content-Type of the stored file")
    link: str = Field(..., description="URL a consumer can GET/stream the file from")
    size_bytes: int = Field(..., description="File size in bytes")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = Field(default=None, description="TTL expiry, if any")
    folder_id: Optional[str] = Field(default=None, description="Backend-specific grouping key")
    status: str = Field(default="active", description="'active' or 'expired'")

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        if self.expires_at is None:
            return False
        return (now or datetime.now(timezone.utc)) >= self.expires_at
