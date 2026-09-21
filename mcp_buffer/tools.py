"""MCP tools for buffer operations."""

from __future__ import annotations

import base64
import binascii
import os
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from .backend import BufferBackend, BufferBackendError


def _public_base() -> str:
    """Base URL callers can reach this server's HTTP routes on."""
    return os.environ.get("MCP_BUFFER_PUBLIC_URL", "http://127.0.0.1:8600").rstrip("/")


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
        if not os.path.isfile(path):
            # Fail loudly: without this check a nonexistent path used to fall
            # through to the backend's text fallback and got stored as the
            # literal path string -- silently corrupt uploads for any caller
            # whose filesystem differs from the buffer host's (e.g. a Mac
            # client calling the public https:// service over MCP).
            return {
                "error": (
                    f"Path '{path}' does not exist on the buffer host "
                    f"('{os.uname().nodename}'). buffer_upload_file reads files "
                    "from the host running this server; remote callers must "
                    "push bytes instead — use buffer_upload_bytes(content_base64=...) "
                    f"or PUT {_public_base()}/buffer/upload?filename=..."
                )
            }
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
    async def buffer_upload_bytes(
        content_base64: str,
        filename: str,
        mime_type: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        folder_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Push base64-encoded content (e.g. an image attached in chat) into
        the buffer and get back a streamable link.

        Use this instead of buffer_upload_file when the caller has no
        filesystem in common with the buffer host — e.g. a photo a chat
        client is holding in-memory. Send the raw bytes base64-encoded as
        a normal JSON-RPC string argument; no shared disk or separate HTTP
        call required.

        Args:
            content_base64: Standard base64 (RFC 4648) of the file bytes.
            filename: Name to store/serve it as.
            mime_type: Content-Type; guessed from filename if omitted.
            ttl_seconds: Optional expiry, relative to now.
            folder_id: Optional grouping key (backend-specific).

        Returns:
            buffer_id, link, filename, mime_type, size_bytes, expires_at;
            or {"error": ...} if the upload failed.
        """
        try:
            raw = base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError) as e:
            return {"error": f"content_base64 is not valid base64: {e}"}
        try:
            entry = await backend.buffer_upload(
                content=raw,
                filename=filename,
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
