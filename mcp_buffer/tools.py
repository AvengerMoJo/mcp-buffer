"""MCP tools for buffer operations."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from .backend import BufferBackend
from .models import BufferEntry


def register_buffer_tools(mcp: FastMCP, backend: BufferBackend) -> None:
    """Register MCP tools for buffer operations with a FastMCP server.

    Args:
        mcp: The FastMCP server instance.
        backend: The buffer backend to use for operations.
    """

    @mcp.tool()
    async def buffer_create(content: str, metadata: dict[str, str] | None = None) -> dict[str, Any]:
        """Create a new buffer entry with content and optional metadata.

        Args:
            content: The content to store in the buffer entry.
            metadata: Optional key-value pairs for additional metadata.

        Returns:
            Information about the created entry including its ID.
        """
        import uuid
        from datetime import datetime, timezone

        entry = BufferEntry(
            id=str(uuid.uuid4()),
            content=content,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            metadata=metadata or {}
        )
        result = await backend.create_entry(entry)
        return {
            "id": result.id,
            "created_at": result.created_at.isoformat(),
            "message": "Entry created successfully"
        }

    @mcp.tool()
    async def buffer_get(entry_id: str) -> dict[str, Any]:
        """Retrieve a buffer entry by its ID.

        Args:
            entry_id: The unique identifier of the entry to retrieve.

        Returns:
            The requested entry's content and metadata, or an error message if not found.
        """
        try:
            entry = await backend.get_entry(entry_id)
            if entry is None:
                return {"error": f"Entry with ID '{entry_id}' not found"}
            return {
                "id": entry.id,
                "content": entry.content,
                "created_at": entry.created_at.isoformat(),
                "updated_at": entry.updated_at.isoformat(),
                "metadata": entry.metadata
            }
        except Exception as e:
            return {"error": f"Failed to retrieve entry: {str(e)}"}

    @mcp.tool()
    async def buffer_update(entry_id: str, content: str) -> dict[str, Any]:
        """Update the content of an existing buffer entry.

        Args:
            entry_id: The unique identifier of the entry to update.
            content: The new content for the entry.

        Returns:
            Confirmation that the entry was updated.
        """
        from datetime import datetime, timezone

        try:
            existing = await backend.get_entry(entry_id)
            if existing is None:
                return {"error": f"Entry with ID '{entry_id}' not found"}

            entry = BufferEntry(
                id=existing.id,
                content=content,
                created_at=existing.created_at,
                updated_at=datetime.now(timezone.utc),
                metadata=existing.metadata
            )
            await backend.update_entry(entry)
            return {
                "id": entry_id,
                "updated_at": entry.updated_at.isoformat(),
                "message": "Entry updated successfully"
            }
        except Exception as e:
            return {"error": f"Failed to update entry: {str(e)}"}

    @mcp.tool()
    async def buffer_list() -> dict[str, Any]:
        """List all buffer entries.

        Returns:
            A summary of all entries including their IDs and creation times.
        """
        try:
            entries = await backend.list_entries()
            return {
                "count": len(entries),
                "entries": [
                    {
                        "id": entry.id,
                        "created_at": entry.created_at.isoformat(),
                        "updated_at": entry.updated_at.isoformat(),
                        "content_preview": entry.content[:100] + "..." if len(entry.content) > 100 else entry.content
                    }
                    for entry in entries
                ]
            }
        except Exception as e:
            return {"error": f"Failed to list entries: {str(e)}"}

    @mcp.tool()
    async def buffer_delete(entry_id: str) -> dict[str, Any]:
        """Delete a buffer entry by its ID.

        Args:
            entry_id: The unique identifier of the entry to delete.

        Returns:
            Confirmation that the entry was deleted or an error message if not found.
        """
        try:
            result = await backend.delete_entry(entry_id)
            if result:
                return {"id": entry_id, "message": "Entry deleted successfully"}
            return {"error": f"Entry with ID '{entry_id}' not found"}
        except Exception as e:
            return {"error": f"Failed to delete entry: {str(e)}"}
