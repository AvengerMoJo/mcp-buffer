#!/usr/bin/env python3
"""Test runner for mcp-buffer Phase 1."""
import sys
from datetime import datetime, timezone

# Add the project directory
sys.path.insert(0, '/home/alex/.memory/mcp-buffer')

from mcp_buffer.models import BufferEntry
from mcp_buffer.registry import BufferRegistry
from mcp_buffer.backend import BufferBackend


def make_entry(**kwargs):
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


def test_buffer_entry_fields():
    """Test BufferEntry dataclass fields."""
    e = make_entry()
    assert e.buffer_id == "test-id", f"Expected 'test-id', got {e.buffer_id}"
    assert e.status == "active", f"Expected 'active', got {e.status}"
    assert e.expires_at is None, f"Expected None, got {e.expires_at}"
    print("  PASSED: test_buffer_entry_fields")


def test_registry_register_and_get():
    """Test registry registration and retrieval."""
    BufferRegistry.register("mock_test")(MockBackend)
    backend = BufferRegistry.get_backend("mock_test")
    assert isinstance(backend, MockBackend), "Expected MockBackend instance"
    print("  PASSED: test_registry_register_and_get")


def test_registry_unknown_raises():
    """Test that unknown backends raise ValueError."""
    try:
        BufferRegistry.get_backend("nonexistent_provider")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unknown buffer backend" in str(e), f"Wrong error message: {e}"
        print("  PASSED: test_registry_unknown_raises")


async def mock_test_backend_upload():
    """Test mock backend upload."""
    backend = MockBackend()
    entry = await backend.buffer_upload(b"hello", "test.txt")
    assert entry.filename == "test.txt", f"Expected 'test.txt', got {entry.filename}"
    assert entry.status == "active", f"Expected 'active', got {entry.status}"
    print("  PASSED: test_mock_backend_upload")


async def mock_test_backend_list():
    """Test mock backend list."""
    backend = MockBackend()
    entries = await backend.list()
    assert len(entries) == 1, f"Expected 1 entry, got {len(entries)}"
    print("  PASSED: test_mock_backend_list")


async def mock_test_backend_can_reuse():
    """Test mock backend can_reuse."""
    backend = MockBackend()
    result = await backend.can_reuse("any-id")
    assert result is True, f"Expected True, got {result}"
    print("  PASSED: test_mock_backend_can_reuse")


async def main():
    """Run all tests."""
    print("\n=== Running mcp-buffer Phase 1 Tests ===\n")

    # Run sync tests first
    test_buffer_entry_fields()
    test_registry_register_and_get()
    test_registry_unknown_raises()

    # Run async tests
    await mock_test_backend_upload()
    await mock_test_backend_list()
    await mock_test_backend_can_reuse()

    print("\n=== All 6 tests PASSED ===\n")


if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
        sys.exit(0)
    except Exception as e:
        print(f"\nFAILED: {e}")
        sys.exit(1)
