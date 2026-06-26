"""MCP tools for buffer operations."""

from mcp import Tool, StringValue
from typing import Any, Callable

from .backend import BufferBackend
from .models import BufferEntry


def create_buffer_tools(backend: BufferBackend) -> list[Tool]:
    """Create MCP tools for buffer operations.

    Args:
        backend: The buffer backend to use for operations.

    Returns:
        A list of MCP Tool instances, each with its handler wired via _meta.
    """

    async def create_entry_tool(content: str, metadata: dict[str, str] = {}) -> dict[str, Any]:
        """Create a new buffer entry with the given content and optional metadata.

        Args:
            content: The content to store in the buffer entry.
            metadata: Optional key-value pairs for additional metadata.

        Returns:
            Information about the created entry including its ID.
        """
        import uuid
        from datetime import datetime

        entry = BufferEntry(
            id=str(uuid.uuid4()),
            content=content,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            metadata=metadata or {}
        )
        result = await backend.create_entry(entry)
        return {
            "id": result.id,
            "created_at": result.created_at.isoformat(),
            "message": "Entry created successfully"
        }

    async def get_entry_tool(entry_id: str) -> dict[str, Any]:
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

    async def update_entry_tool(entry_id: str, content: str) -> dict[str, Any]:
        """Update the content of an existing buffer entry.

        Args:
            entry_id: The unique identifier of the entry to update.
            content: The new content for the entry.

        Returns:
            Confirmation that the entry was updated.
        """
        try:
            # First get the existing entry to preserve metadata and timestamps
            existing = await backend.get_entry(entry_id)
            if existing is None:
                return {"error": f"Entry with ID '{entry_id}' not found"}

            entry = BufferEntry(
                id=existing.id,
                content=content,
                created_at=existing.created_at,
                updated_at=existing.updated_at,  # Will be updated by model
                metadata=existing.metadata
            )
            await backend.update_entry(entry)
            return {
                "id": entry_id,
                "updated_at": datetime.utcnow().isoformat(),
                "message": "Entry updated successfully"
            }
        except Exception as e:
            return {"error": f"Failed to update entry: {str(e)}"}

    async def list_entries_tool() -> dict[str, Any]:
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

    async def delete_entry_tool(entry_id: str) -> dict[str, Any]:
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

    # Wire each handler to its corresponding Tool via _meta["handler"]
    handlers = [create_entry_tool, get_entry_tool, update_entry_tool, list_entries_tool, delete_entry_tool]

    return [
        Tool(
            name="buffer_create",
            description="Create a new buffer entry with content and optional metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The content to store"},
                    "metadata": {"type": "object", "description": "Optional key-value metadata"}
                },
                "required": ["content"]
            },
            _meta={"handler": handlers[0]}
        ),
        Tool(
            name="buffer_get",
            description="Retrieve a buffer entry by its ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string", "description": "The unique identifier of the entry"}
                },
                "required": ["entry_id"]
            },
            _meta={"handler": handlers[1]}
        ),
        Tool(
            name="buffer_update",
            description="Update the content of an existing buffer entry.",
            inputSchema={
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string", "description": "The unique identifier of the entry"},
                    "content": {"type": "string", "description": "The new content"}
                },
                "required": ["entry_id", "content"]
            },
            _meta={"handler": handlers[2]}
        ),
        Tool(
            name="buffer_list",
            description="List all buffer entries with summaries.",
            inputSchema={
                "type": "object",
                "properties": {}
            },
            _meta={"handler": handlers[3]}
        ),
        Tool(
            name="buffer_delete",
            description="Delete a buffer entry by its ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string", "description": "The unique identifier of the entry to delete"}
                },
                "required": ["entry_id"]
            },
            _meta={"handler": handlers[4]}
        )
    ]
