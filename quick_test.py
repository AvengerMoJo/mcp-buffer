import sys
sys.path.insert(0, '/home/alex/.memory/mcp-buffer')

from datetime import datetime, timezone
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


print("Running test_buffer_entry_fields...")
e = make_entry()
assert e.buffer_id == "test-id", f"Expected 'test-id', got {e.buffer_id}"
assert e.status == "active", f"Expected 'active', got {e.status}"
assert e.expires_at is None, f"Expected None, got {e.expires_at}"
print("  PASSED")

print("Running test_registry_register_and_get...")
BufferRegistry.register("mock_test")(MockBackend)
backend = BufferRegistry.get_backend("mock_test")
assert isinstance(backend, MockBackend), "Expected MockBackend instance"
print("  PASSED")

print("Running test_registry_unknown_raises...")
try:
    BufferRegistry.get_backend("nonexistent_provider")
    assert False, "Should have raised ValueError"
except ValueError as e:
    assert "Unknown buffer backend" in str(e), f"Wrong error message: {e}"
print("  PASSED")

print("\nAll tests passed!")
