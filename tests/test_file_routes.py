"""Tests for the buffered-file HTTP route (file_routes.py), mounted onto a
real FastMCP app and exercised through Starlette's TestClient -- actual
ASGI request/response handling, not just direct function calls.
"""

from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP
from starlette.testclient import TestClient

from mcp_buffer import file_routes
from mcp_buffer.backend import BufferBackend
from mcp_buffer.local_backend import LocalFileBackend


class _UploadBackend(BufferBackend):
    """Minimal backend over LocalFileBackend so the upload route can be
    exercised end-to-end through a real ASGI app."""

    def __init__(self, store_dir):
        self._inner = LocalFileBackend(store_dir=str(store_dir))

    async def buffer_upload(self, content, filename, mime_type=None, ttl_seconds=None, folder_id=None):
        return await self._inner.buffer_upload(content, filename, mime_type, ttl_seconds, folder_id)

    async def get_link(self, buffer_id):
        return await self._inner.get_link(buffer_id)

    async def expire(self, buffer_id):
        await self._inner.expire(buffer_id)

    async def list(self, folder_id=None):
        return await self._inner.list(folder_id)

    async def can_reuse(self, buffer_id):
        return await self._inner.can_reuse(buffer_id)


@pytest.fixture
def client(tmp_path):
    mcp = FastMCP("test-mcp-buffer")
    # Upload route registered first -- same ordering server.py uses so
    # /buffer/upload isn't shadowed by /buffer/{buffer_id}.
    file_routes.register_upload_route(mcp, _UploadBackend(tmp_path))
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

    def test_named_route_uses_extension_for_content_type(self, client, tmp_path):
        # Stored as text/plain but requested via a .pdf name -> NotebookLM et
        # al. get a PDF content-type and treat the bytes accordingly.
        _write(tmp_path, "idpdf", b"%PDF-1.4 fake", mime_type="text/plain")
        resp = client.get("/buffer/idpdf/report.pdf")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/pdf"
        assert resp.content == b"%PDF-1.4 fake"

    def test_named_route_matches_unnamed(self, client, tmp_path):
        _write(tmp_path, "idtxt", b"hello world")
        resp = client.get("/buffer/idtxt/notes.txt")
        assert resp.status_code == 200
        assert resp.content == b"hello world"

    def test_named_route_unknown_buffer_id_404s(self, client):
        resp = client.get("/buffer/nope/report.pdf")
        assert resp.status_code == 404

    def test_format_text_overrides_content_type(self, client, tmp_path):
        _write(tmp_path, "idt", b"<html>not really</html>", mime_type="text/html")
        resp = client.get("/buffer/idt?format=text")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/plain; charset=utf-8"
        assert resp.content == b"<html>not really</html>"

    def test_format_html_wraps_body_in_page(self, client, tmp_path):
        _write(tmp_path, "idh", b"line one\nline two", mime_type="text/plain")
        resp = client.get("/buffer/idh?format=html")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "text/html; charset=utf-8"
        assert b"<pre>line one" in resp.content
        assert b"</html>" in resp.content

    def test_format_unknown_400s(self, client, tmp_path):
        _write(tmp_path, "idb", b"x", mime_type="text/plain")
        resp = client.get("/buffer/idb?format=docx")
        assert resp.status_code == 400


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


class TestUpload:
    def test_put_raw_bytes_returns_json_with_working_link(self, client):
        resp = client.put(
            "/buffer/upload?filename=report.pdf",
            content=b"%PDF-1.4 fake pdf bytes",
            headers={"Content-Type": "application/pdf"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["filename"] == "report.pdf"
        assert data["mime_type"] == "application/pdf"
        assert data["size_bytes"] == len(b"%PDF-1.4 fake pdf bytes")
        # The link it hands back must actually serve the same bytes.
        got = client.get(f"/buffer/{data['buffer_id']}")
        assert got.status_code == 200
        assert got.content == b"%PDF-1.4 fake pdf bytes"

    def test_post_also_accepted(self, client):
        resp = client.post("/buffer/upload?filename=a.txt", content=b"aaa")
        assert resp.status_code == 201

    def test_mime_type_falls_back_to_content_type_header(self, client):
        resp = client.put(
            "/buffer/upload?filename=x.bin",
            content=b"\x00\x01",
            headers={"Content-Type": "application/custom; charset=binary"},
        )
        assert resp.json()["mime_type"] == "application/custom"

    def test_mime_type_guessed_from_filename_when_no_header(self, client):
        resp = client.put("/buffer/upload?filename=doc.pdf", content=b"x")
        assert resp.json()["mime_type"] == "application/pdf"

    def test_explicit_mime_query_param_wins(self, client):
        resp = client.put(
            "/buffer/upload?filename=doc.pdf&mime_type=application/x-thing",
            content=b"x",
            headers={"Content-Type": "application/pdf"},
        )
        assert resp.json()["mime_type"] == "application/x-thing"

    def test_default_filename_when_missing(self, client):
        resp = client.put("/buffer/upload", content=b"anon")
        assert resp.json()["filename"] == "upload.bin"

    def test_empty_body_400s(self, client):
        resp = client.put("/buffer/upload?filename=e.txt")
        assert resp.status_code == 400

    def test_bad_ttl_400s(self, client):
        resp = client.put("/buffer/upload?filename=t.txt&ttl_seconds=soon", content=b"x")
        assert resp.status_code == 400
        assert "integer" in resp.text

    def test_ttl_sets_expires_at(self, client):
        resp = client.put("/buffer/upload?filename=t.txt&ttl_seconds=3600", content=b"x")
        assert resp.json()["expires_at"] is not None

    def test_upload_route_not_shadowed_by_download_route(self, client):
        # GET /buffer/{buffer_id} would match the path /buffer/upload; the
        # PUT route registered before it must win for uploads.
        resp = client.put("/buffer/upload?filename=s.txt", content=b"shadow check")
        assert resp.status_code == 201
