"""Tests for the MCP tool surface (tools.py), especially the guard that
stops nonexistent paths from being silently stored as text."""

from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP

from mcp_buffer.local_backend import LocalFileBackend
from mcp_buffer.tools import register_buffer_tools


@pytest.fixture
def mcp(tmp_path):
    mcp = FastMCP("test-tools")
    register_buffer_tools(mcp, LocalFileBackend(store_dir=str(tmp_path)))
    return mcp


class TestBufferUploadFilePathGuard:
    @pytest.mark.asyncio
    async def test_nonexistent_path_returns_error_not_a_stored_string(self, mcp):
        result = await mcp.call_tool(
            "buffer_upload_file",
            {"path": "/Users/alex/Downloads/nope.pdf"},
        )
        # call_tool returns (content_blocks, raw) in newer MCP SDKs; find
        # the error payload either way.
        payload = _payload(result)
        assert "error" in payload
        assert "does not exist on the buffer host" in payload["error"]

    @pytest.mark.asyncio
    async def test_existing_file_uploads_normally(self, mcp, tmp_path):
        src = tmp_path / "real.pdf"
        src.write_bytes(b"%PDF-1.4 bytes")
        result = await mcp.call_tool(
            "buffer_upload_file",
            {"path": str(src)},
        )
        payload = _payload(result)
        assert "error" not in payload
        assert payload["size_bytes"] == len(b"%PDF-1.4 bytes")


def _payload(result):
    """Normalize call_tool output across SDK shapes down to the dict the
    tool returned."""
    if isinstance(result, tuple):
        content = result[0]
    else:
        content = result
    if isinstance(content, list):
        for block in content:
            text = getattr(block, "text", None)
            if text is None and isinstance(block, dict):
                text = block.get("text")
            if text:
                import json

                return json.loads(text)
    if isinstance(content, dict):
        return content
    raise AssertionError(f"Unexpected tool result shape: {result!r}")
