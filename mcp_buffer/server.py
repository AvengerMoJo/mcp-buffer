"""MCP server for mcp-buffer."""

import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .backend import BufferBackend
from .google_drive import GoogleDriveBuffer
from .registry import BufferRegistry
from .tools import register_buffer_tools


def create_server() -> FastMCP:
    """Create and configure the MCP server.

    Returns:
        Configured FastMCP server instance.
    """
    mcp = FastMCP("mcp-buffer")

    # Get the backend from environment or default to Google Drive
    backend_name = os.environ.get("MCP_BUFFER_BACKEND", "google_drive")

    if backend_name == "google_drive":
        sheet_id = os.environ.get("MCP_BUFFER_DRIVE_SHEET_ID")
        if not sheet_id:
            print("Error: MCP_BUFFER_DRIVE_SHEET_ID environment variable is required for Google Drive backend")
            sys.exit(1)
        backend = GoogleDriveBuffer(sheet_id=sheet_id)
    else:
        # Try to get from registry
        try:
            backend = BufferRegistry.get_backend(backend_name)
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)

    # Register tools
    register_buffer_tools(mcp, backend)

    return mcp


def main():
    """Main entry point for the MCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="MCP Buffer Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio",
                       help="Transport type (default: stdio)")
    parser.add_argument("--host", default="0.0.0.0",
                       help="Host to bind to (for SSE transport)")
    parser.add_argument("--port", type=int, default=8001,
                       help="Port to bind to (for SSE transport)")
    args = parser.parse_args()

    mcp = create_server()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="sse", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
