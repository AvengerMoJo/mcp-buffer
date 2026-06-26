"""Data models for mcp-buffer."""

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class BufferEntry(BaseModel):
    """An entry in the buffer."""

    id: str = Field(..., description="Unique identifier for this entry")
    content: str = Field(..., description="Content of the buffer entry")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="When this entry was created")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="When this entry was last updated")
    metadata: dict[str, str] = Field(default_factory=dict, description="Additional metadata")

    def update(self) -> None:
        """Update the timestamp when modified."""
        self.updated_at = datetime.utcnow()
