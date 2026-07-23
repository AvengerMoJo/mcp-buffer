"""Tests for the buffered-file HTTP route (file_routes.py), mounted onto a
real FastMCP app and exercised through Starlette's TestClient -- actual
ASGI request/response handling, not just direct function calls.
"""

from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP
from starlette.testclient import TestClient

from mcp_buffer import file_routes


@pytest.fixture
def client(tmp_path):
    mcp = FastMCP("test-mcp-buffer")
    file_routes.register_file_route(mcp)
    app = mcp.streamable_http_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clear_registry():
    yield
    file_routes._registry.clear()


def _write(tmp_path, buffer_id: str, content: bytes, mime_type: str = "text/plain"):
    path = tmp_path / buffer_id
    path.write_bytes(content)
    file_routes.register(buffer_id, str(path), mime_type)
    return path


class TestGet:
    def test_get_returns_full_content(self, client, tmp_path):
        _write(tmp_path, "id1", b"hello world")
        resp = client.get("/buffer/id1")
        assert resp.status_code == 200
        assert resp.content == b"hello world"
        assert resp.headers["content-type"] == "text/plain"
        assert resp.headers["accept-ranges"] == "bytes"

    def test_get_unknown_buffer_id_404s(self, client):
        resp = client.get("/buffer/does-not-exist")
        assert resp.status_code == 404

    def test_get_after_unregister_404s(self, client, tmp_path):
        _write(tmp_path, "id2", b"gone soon")
        file_routes.unregister("id2")
        resp = client.get("/buffer/id2")
        assert resp.status_code == 404

    def test_get_missing_file_on_disk_404s(self, client, tmp_path):
        path = tmp_path / "id3"
        path.write_bytes(b"will be deleted")
        file_routes.register("id3", str(path), "text/plain")
        path.unlink()
        resp = client.get("/buffer/id3")
        assert resp.status_code == 404


class TestHead:
    def test_head_returns_headers_no_body(self, client, tmp_path):
        _write(tmp_path, "id4", b"head me")
        resp = client.head("/buffer/id4")
        assert resp.status_code == 200
        assert resp.headers["content-length"] == str(len(b"head me"))
        assert resp.content == b""


class TestRange:
    def test_partial_range_returns_206(self, client, tmp_path):
        _write(tmp_path, "id5", b"0123456789")
        resp = client.get("/buffer/id5", headers={"Range": "bytes=2-5"})
        assert resp.status_code == 206
        assert resp.content == b"2345"
        assert resp.headers["content-range"] == "bytes 2-5/10"

    def test_open_ended_range_reads_to_eof(self, client, tmp_path):
        _write(tmp_path, "id6", b"0123456789")
        resp = client.get("/buffer/id6", headers={"Range": "bytes=7-"})
        assert resp.status_code == 206
        assert resp.content == b"789"

    def test_range_end_beyond_size_is_clamped(self, client, tmp_path):
        _write(tmp_path, "id7", b"short")
        resp = client.get("/buffer/id7", headers={"Range": "bytes=0-999"})
        assert resp.status_code == 206
        assert resp.content == b"short"

    def test_no_range_header_returns_full_200(self, client, tmp_path):
        _write(tmp_path, "id8", b"whole thing")
        resp = client.get("/buffer/id8")
        assert resp.status_code == 200
        assert resp.content == b"whole thing"


class TestRegistry:
    def test_register_then_unregister_removes_entry(self):
        file_routes.register("rid", "/tmp/whatever", "text/plain")
        assert file_routes._resolve("rid") == ("/tmp/whatever", "text/plain")
        file_routes.unregister("rid")
        assert file_routes._resolve("rid") is None

    def test_unregister_unknown_id_is_a_noop(self):
        file_routes.unregister("never-registered")  # must not raise
