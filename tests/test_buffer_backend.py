"""Tests for the BufferBackend contract, LocalFileBackend, and BufferRegistry."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from mcp_buffer.backend import BufferBackend, BufferBackendError
from mcp_buffer.local_backend import LocalFileBackend
from mcp_buffer.models import BufferEntry
from mcp_buffer.registry import BufferRegistry


def make_entry(**kwargs) -> BufferEntry:
    defaults = dict(
        buffer_id="test-id",
        provider="mock",
        filename="test.txt",
        mime_type="text/plain",
        link="https://example.com/test",
        size_bytes=100,
        created_at=datetime.now(timezone.utc),
        expires_at=None,
        folder_id=None,
        status="active",
    )
    return BufferEntry(**{**defaults, **kwargs})


class MockBackend(BufferBackend):
    async def buffer_upload(self, content, filename, mime_type=None, ttl_seconds=None, folder_id=None):
        return make_entry(filename=filename)

    async def get_link(self, buffer_id):
        return "https://example.com/mock"

    async def expire(self, buffer_id):
        pass

    async def list(self, folder_id=None):
        return [make_entry()]

    async def can_reuse(self, buffer_id):
        return True


class TestBufferEntry:
    def test_fields(self):
        e = make_entry()
        assert e.buffer_id == "test-id"
        assert e.status == "active"
        assert e.expires_at is None

    def test_is_expired_with_no_expiry(self):
        assert make_entry(expires_at=None).is_expired() is False

    def test_is_expired_past(self):
        past = datetime(2000, 1, 1, tzinfo=timezone.utc)
        assert make_entry(expires_at=past).is_expired() is True

    def test_is_expired_future(self):
        future = datetime(2999, 1, 1, tzinfo=timezone.utc)
        assert make_entry(expires_at=future).is_expired() is False


class TestBufferRegistry:
    def setup_method(self):
        BufferRegistry._reset_for_tests()

    def test_register_and_get(self):
        BufferRegistry.register("mock_test")(MockBackend)
        backend = BufferRegistry.get_backend("mock_test")
        assert isinstance(backend, MockBackend)

    def test_get_returns_cached_instance(self):
        BufferRegistry.register("mock_test2")(MockBackend)
        first = BufferRegistry.get_backend("mock_test2")
        second = BufferRegistry.get_backend("mock_test2")
        assert first is second

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown buffer backend"):
            BufferRegistry.get_backend("nonexistent_provider")

    def test_local_backend_is_registered_by_import(self):
        import mcp_buffer.local_backend  # noqa: F401

        assert "local" in BufferRegistry.known_backends()


@pytest.fixture
def local_backend(tmp_path) -> LocalFileBackend:
    return LocalFileBackend(store_dir=str(tmp_path))


class TestLocalFileBackendUpload:
    @pytest.mark.asyncio
    async def test_upload_raw_bytes(self, local_backend: LocalFileBackend):
        entry = await local_backend.buffer_upload(b"hello world", filename="hello.txt")
        assert entry.filename == "hello.txt"
        assert entry.size_bytes == len(b"hello world")
        assert entry.mime_type == "text/plain"
        assert entry.provider == "local"
        assert entry.link.startswith("http://127.0.0.1:")

    @pytest.mark.asyncio
    async def test_upload_from_local_file_path(self, local_backend: LocalFileBackend, tmp_path):
        src = tmp_path / "source.pdf"
        src.write_bytes(b"%PDF-1.4 fake pdf bytes")
        entry = await local_backend.buffer_upload(str(src), filename="source.pdf")
        assert entry.mime_type == "application/pdf"
        assert entry.size_bytes == src.stat().st_size

    @pytest.mark.asyncio
    async def test_upload_raw_text_content_not_a_path(self, local_backend: LocalFileBackend):
        entry = await local_backend.buffer_upload("just some text", filename="note.txt")
        assert entry.size_bytes == len(b"just some text")

    @pytest.mark.asyncio
    async def test_explicit_mime_type_overrides_guess(self, local_backend: LocalFileBackend):
        entry = await local_backend.buffer_upload(b"data", filename="file.bin", mime_type="application/custom")
        assert entry.mime_type == "application/custom"

    @pytest.mark.asyncio
    async def test_ttl_sets_expiry(self, local_backend: LocalFileBackend):
        entry = await local_backend.buffer_upload(b"data", filename="f.txt", ttl_seconds=3600)
        assert entry.expires_at is not None
        assert entry.expires_at > datetime.now(timezone.utc)


class TestLocalFileBackendLinkAndStream:
    @pytest.mark.asyncio
    async def test_get_link_returns_working_url(self, local_backend: LocalFileBackend):
        import urllib.request

        entry = await local_backend.buffer_upload(b"stream me", filename="s.txt")
        link = await local_backend.get_link(entry.buffer_id)
        assert link == entry.link
        with urllib.request.urlopen(link, timeout=5) as resp:
            assert resp.read() == b"stream me"
            assert resp.headers.get("Content-Type") == "text/plain"

    @pytest.mark.asyncio
    async def test_range_request_is_honored(self, local_backend: LocalFileBackend):
        import urllib.request

        entry = await local_backend.buffer_upload(b"0123456789", filename="range.bin")
        req = urllib.request.Request(entry.link, headers={"Range": "bytes=2-5"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 206
            assert resp.read() == b"2345"

    @pytest.mark.asyncio
    async def test_head_request_returns_headers_no_body(self, local_backend: LocalFileBackend):
        import urllib.request

        entry = await local_backend.buffer_upload(b"head me", filename="h.txt")
        req = urllib.request.Request(entry.link, method="HEAD")
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Length") == str(len(b"head me"))
            assert resp.read() == b""

    @pytest.mark.asyncio
    async def test_get_link_unknown_id_raises(self, local_backend: LocalFileBackend):
        with pytest.raises(BufferBackendError):
            await local_backend.get_link("does-not-exist")

    @pytest.mark.asyncio
    async def test_get_link_after_expire_raises(self, local_backend: LocalFileBackend):
        entry = await local_backend.buffer_upload(b"gone soon", filename="g.txt")
        await local_backend.expire(entry.buffer_id)
        with pytest.raises(BufferBackendError):
            await local_backend.get_link(entry.buffer_id)

    @pytest.mark.asyncio
    async def test_ttl_expiry_is_enforced_on_access(self, local_backend: LocalFileBackend):
        entry = await local_backend.buffer_upload(b"short lived", filename="t.txt", ttl_seconds=0)
        time.sleep(0.01)
        assert await local_backend.can_reuse(entry.buffer_id) is False
        with pytest.raises(BufferBackendError):
            await local_backend.get_link(entry.buffer_id)


class TestLocalFileBackendExpireAndList:
    @pytest.mark.asyncio
    async def test_expire_unknown_raises(self, local_backend: LocalFileBackend):
        with pytest.raises(BufferBackendError):
            await local_backend.expire("does-not-exist")

    @pytest.mark.asyncio
    async def test_expire_removes_file_from_disk(self, local_backend: LocalFileBackend, tmp_path):
        entry = await local_backend.buffer_upload(b"bye", filename="bye.txt")
        stored_path = tmp_path / entry.buffer_id
        assert stored_path.is_file()
        await local_backend.expire(entry.buffer_id)
        assert not stored_path.is_file()

    @pytest.mark.asyncio
    async def test_list_excludes_expired(self, local_backend: LocalFileBackend):
        keep = await local_backend.buffer_upload(b"keep", filename="keep.txt")
        gone = await local_backend.buffer_upload(b"gone", filename="gone.txt")
        await local_backend.expire(gone.buffer_id)

        entries = await local_backend.list()
        ids = [e.buffer_id for e in entries]
        assert keep.buffer_id in ids
        assert gone.buffer_id not in ids

    @pytest.mark.asyncio
    async def test_list_sorted_newest_first(self, local_backend: LocalFileBackend):
        first = await local_backend.buffer_upload(b"1", filename="1.txt")
        second = await local_backend.buffer_upload(b"2", filename="2.txt")
        entries = await local_backend.list()
        assert entries[0].buffer_id == second.buffer_id
        assert entries[1].buffer_id == first.buffer_id

    @pytest.mark.asyncio
    async def test_list_filters_by_folder_id(self, local_backend: LocalFileBackend):
        await local_backend.buffer_upload(b"a", filename="a.txt", folder_id="alpha")
        beta = await local_backend.buffer_upload(b"b", filename="b.txt", folder_id="beta")

        entries = await local_backend.list(folder_id="beta")
        assert [e.buffer_id for e in entries] == [beta.buffer_id]

    @pytest.mark.asyncio
    async def test_can_reuse_true_for_active_entry(self, local_backend: LocalFileBackend):
        entry = await local_backend.buffer_upload(b"x", filename="x.txt")
        assert await local_backend.can_reuse(entry.buffer_id) is True

    @pytest.mark.asyncio
    async def test_can_reuse_false_for_unknown(self, local_backend: LocalFileBackend):
        assert await local_backend.can_reuse("nope") is False


class TestLocalFileBackendPublicUrl:
    @pytest.mark.asyncio
    async def test_public_url_env_var_overrides_link_host(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MCP_BUFFER_PUBLIC_URL", "https://buffer.eclipsogate.org")
        backend = LocalFileBackend(store_dir=str(tmp_path))
        entry = await backend.buffer_upload(b"public", filename="p.txt")
        assert entry.link == f"https://buffer.eclipsogate.org/{entry.buffer_id}"

    @pytest.mark.asyncio
    async def test_public_url_trailing_slash_is_stripped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MCP_BUFFER_PUBLIC_URL", "https://buffer.eclipsogate.org/")
        backend = LocalFileBackend(store_dir=str(tmp_path))
        entry = await backend.buffer_upload(b"public", filename="p.txt")
        assert entry.link == f"https://buffer.eclipsogate.org/{entry.buffer_id}"

    @pytest.mark.asyncio
    async def test_no_public_url_falls_back_to_local_server(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MCP_BUFFER_PUBLIC_URL", raising=False)
        backend = LocalFileBackend(store_dir=str(tmp_path))
        entry = await backend.buffer_upload(b"local", filename="l.txt")
        assert entry.link.startswith("http://127.0.0.1:")


class TestLocalFileBackendPersistence:
    @pytest.mark.asyncio
    async def test_index_survives_reload(self, tmp_path):
        backend1 = LocalFileBackend(store_dir=str(tmp_path))
        entry = await backend1.buffer_upload(b"persisted", filename="p.txt")

        backend2 = LocalFileBackend(store_dir=str(tmp_path))
        reloaded = await backend2.list()
        assert any(e.buffer_id == entry.buffer_id for e in reloaded)
