"""MCP server for mcp-buffer."""

import os
import sys

from mcp.server.fastmcp import FastMCP

# Importing local_backend registers "local" with BufferRegistry as a side
# effect (the @BufferRegistry.register("local") decorator). Any additional
# backend module (google_drive, onedrive, s3, nextcloud, ...) should be
# imported the same way to make itself available here.
from . import local_backend  # noqa: F401
from .registry import BufferRegistry
from .tools import register_buffer_tools


def create_server(host: str = "127.0.0.1", port: int = 8001) -> FastMCP:
    """Create and configure the MCP server.

    host/port only matter for the "sse"/"streamable-http" transports --
    FastMCP takes them as constructor args, not run() kwargs.
    """
    mcp = FastMCP("mcp-buffer", host=host, port=port)

    backend_name = os.environ.get("MCP_BUFFER_BACKEND", "local")
    try:
        backend = BufferRegistry.get_backend(backend_name)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

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

    mcp = create_server(host=args.host, port=args.port)

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="sse")


if __name__ == "__main__":
    main()
