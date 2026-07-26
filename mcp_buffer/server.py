"""MCP server for mcp-buffer.

Serves both the MCP protocol (streamable-http, the current standard --
not SSE, which is being superseded and doesn't play as nicely with
reverse proxies/tunnels) and the buffered-file download route on the
same port, via FastMCP.custom_route(). One process, one port, one
hostname -- see file_routes.py for why this replaced an earlier design
that ran file-serving on a second, separate socket.
"""

import os
import sys
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

# Importing local_backend registers "local" with BufferRegistry as a side
# effect (the @BufferRegistry.register("local") decorator). Any additional
# backend module (google_drive, onedrive, s3, nextcloud, ...) should be
# imported the same way to make itself available here.
from . import local_backend  # noqa: F401
from .file_routes import register_file_route
from .registry import BufferRegistry
from .tools import register_buffer_tools

_DEFAULT_PORT = 8600

# FastMCP's own default TransportSecuritySettings only allows
# 127.0.0.1/localhost/[::1] Host headers (DNS-rebinding protection). Any
# request arriving through a reverse proxy/tunnel with a different Host
# header -- e.g. Cloudflare Tunnel forwarding Host: buffer.eclipsogate.org
# -- gets a blanket 421 "Invalid Host header" with no other explanation.
# Found live 2026-07-26: the /mcp endpoint worked over plain localhost but
# 421'd for every request through the public domain, including ones with
# fully valid MCP payloads -- reproduced by spoofing the Host header on a
# local curl call. Keep protection ON (it's a real defense), just extend
# the allowlist with MCP_BUFFER_PUBLIC_URL's hostname when set.
_DEFAULT_ALLOWED_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
_DEFAULT_ALLOWED_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]


def _transport_security() -> TransportSecuritySettings:
    allowed_hosts = list(_DEFAULT_ALLOWED_HOSTS)
    allowed_origins = list(_DEFAULT_ALLOWED_ORIGINS)
    public_url = os.environ.get("MCP_BUFFER_PUBLIC_URL")
    if public_url:
        parsed = urlparse(public_url)
        if parsed.hostname:
            allowed_hosts.append(parsed.hostname)
            allowed_hosts.append(f"{parsed.hostname}:*")
            allowed_origins.append(f"{parsed.scheme}://{parsed.hostname}")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


def create_server(host: str = "127.0.0.1", port: int = _DEFAULT_PORT) -> FastMCP:
    """Create and configure the MCP server.

    host/port only matter for the "http"/"sse" transports -- FastMCP
    takes them as constructor args, not run() kwargs.
    """
    mcp = FastMCP("mcp-buffer", host=host, port=port, transport_security=_transport_security())

    backend_name = os.environ.get("MCP_BUFFER_BACKEND", "local")
    try:
        backend = BufferRegistry.get_backend(backend_name)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    register_buffer_tools(mcp, backend)
    if backend_name == "local":
        register_file_route(mcp)
    return mcp


def main():
    """Main entry point for the MCP server."""
    import argparse

    parser = argparse.ArgumentParser(description="MCP Buffer Server")
    parser.add_argument("--transport", choices=["stdio", "http", "sse"], default="stdio",
                       help="Transport type (default: stdio). 'http' (streamable-http) "
                            "is the current MCP standard; 'sse' is kept only for older clients.")
    parser.add_argument("--host", default="0.0.0.0",
                       help="Host to bind to (for http/sse transport)")
    parser.add_argument("--port", type=int, default=_DEFAULT_PORT,
                       help="Port to bind to (for http/sse transport)")
    args = parser.parse_args()

    mcp = create_server(host=args.host, port=args.port)

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    elif args.transport == "http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="sse")


if __name__ == "__main__":
    main()
