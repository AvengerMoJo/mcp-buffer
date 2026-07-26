"""Tests for server.py's TransportSecuritySettings wiring.

FastMCP's own default only allows Host headers matching 127.0.0.1/localhost/
[::1] -- a request arriving through a reverse proxy/tunnel with any other
Host header gets a blanket 421 "Invalid Host header", regardless of how
valid the MCP payload is. Found live 2026-07-26: the public
https://buffer.eclipsogate.org/mcp endpoint 421'd on every call because
this was never configured. These tests exercise real ASGI requests through
Starlette's TestClient (not just inspecting the settings object) so a
regression here fails loudly instead of silently 421-ing in production.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from mcp_buffer.server import _transport_security, create_server

_INITIALIZE_PAYLOAD = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1.0"},
    },
}
_MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


class TestTransportSecuritySettings:
    def test_default_allows_only_localhost_variants(self, monkeypatch):
        monkeypatch.delenv("MCP_BUFFER_PUBLIC_URL", raising=False)
        settings = _transport_security()
        assert settings.enable_dns_rebinding_protection is True
        assert "127.0.0.1:*" in settings.allowed_hosts
        assert "localhost:*" in settings.allowed_hosts
        assert "[::1]:*" in settings.allowed_hosts

    def test_public_url_hostname_is_added_to_allowlist(self, monkeypatch):
        monkeypatch.setenv("MCP_BUFFER_PUBLIC_URL", "https://buffer.eclipsogate.org")
        settings = _transport_security()
        assert "buffer.eclipsogate.org" in settings.allowed_hosts
        assert "buffer.eclipsogate.org:*" in settings.allowed_hosts
        assert "https://buffer.eclipsogate.org" in settings.allowed_origins

    def test_public_url_does_not_remove_localhost_defaults(self, monkeypatch):
        monkeypatch.setenv("MCP_BUFFER_PUBLIC_URL", "https://buffer.eclipsogate.org")
        settings = _transport_security()
        assert "127.0.0.1:*" in settings.allowed_hosts
        assert "localhost:*" in settings.allowed_hosts


def _make_app(tmp_path, monkeypatch):
    monkeypatch.setenv("MCP_BUFFER_LOCAL_DIR", str(tmp_path))
    monkeypatch.setenv("MCP_BUFFER_PUBLIC_URL", "https://buffer.eclipsogate.org")
    mcp = create_server()
    return mcp.streamable_http_app()


class TestMcpEndpointHostHeaderHandling:
    def test_configured_public_hostname_is_accepted(self, tmp_path, monkeypatch):
        app = _make_app(tmp_path, monkeypatch)
        with TestClient(app, base_url="https://buffer.eclipsogate.org") as client:
            resp = client.post("/mcp", json=_INITIALIZE_PAYLOAD, headers=_MCP_HEADERS)
        assert resp.status_code != 421

    def test_unconfigured_hostname_is_still_rejected(self, tmp_path, monkeypatch):
        """Protection must stay real -- an arbitrary spoofed Host should
        still 421, only the explicitly configured public hostname is let
        through."""
        app = _make_app(tmp_path, monkeypatch)
        with TestClient(app, base_url="https://evil.example.com") as client:
            resp = client.post("/mcp", json=_INITIALIZE_PAYLOAD, headers=_MCP_HEADERS)
        assert resp.status_code == 421
