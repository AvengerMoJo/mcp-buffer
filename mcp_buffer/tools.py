"""MCP tools for buffer operations."""

from __future__ import annotations

import os
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from .backend import BufferBackend, BufferBackendError


def register_buffer_tools(mcp: FastMCP, backend: BufferBackend) -> None:
    """Register MCP tools for buffer operations with a FastMCP server."""

    @mcp.tool()
    async def buffer_upload_file(
        path: str,
        filename: Optional[str] = None,
        mime_type: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        folder_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Push a local file into the buffer and get back a streamable link.

        Use this when you have a file on disk you can't process directly
        (too large, wrong format, needs a backend that can decode it) and
        need to hand it off by URL instead of by JSON-RPC payload.

        Args:
            path: Local filesystem path of the file to buffer.
            filename: Name to store/serve it as; defaults to path's basename.
            mime_type: Content-Type; guessed from filename if omitted.
            ttl_seconds: Optional expiry, relative to now.
            folder_id: Optional grouping key (backend-specific).

        Returns:
            buffer_id, link, filename, mime_type, size_bytes, expires_at;
            or {"error": ...} if the upload failed.
        """
        resolved_filename = filename or os.path.basename(path)
        try:
            entry = await backend.buffer_upload(
                content=path,
                filename=resolved_filename,
                mime_type=mime_type,
                ttl_seconds=ttl_seconds,
                folder_id=folder_id,
            )
        except BufferBackendError as e:
            return {"error": str(e)}
        return {
            "buffer_id": entry.buffer_id,
            "link": entry.link,
            "filename": entry.filename,
            "mime_type": entry.mime_type,
            "size_bytes": entry.size_bytes,
            "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
        }

    @mcp.tool()
    async def buffer_get_link(buffer_id: str) -> dict[str, Any]:
        """Return the streamable link for a previously buffered file."""
        try:
            link = await backend.get_link(buffer_id)
        except BufferBackendError as e:
            return {"error": str(e)}
        return {"buffer_id": buffer_id, "link": link}

    @mcp.tool()
    async def buffer_list(folder_id: Optional[str] = None) -> dict[str, Any]:
        """List active buffered files, newest first."""
        entries = await backend.list(folder_id=folder_id)
        return {
            "count": len(entries),
            "entries": [
                {
                    "buffer_id": e.buffer_id,
                    "filename": e.filename,
                    "mime_type": e.mime_type,
                    "link": e.link,
                    "size_bytes": e.size_bytes,
                    "created_at": e.created_at.isoformat(),
                    "expires_at": e.expires_at.isoformat() if e.expires_at else None,
                }
                for e in entries
            ],
        }

    @mcp.tool()
    async def buffer_expire(buffer_id: str) -> dict[str, Any]:
        """Expire a buffered file and release its storage."""
        try:
            await backend.expire(buffer_id)
        except BufferBackendError as e:
            return {"error": str(e)}
        return {"buffer_id": buffer_id, "message": "Entry expired successfully"}
