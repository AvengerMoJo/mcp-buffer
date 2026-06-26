"""Tests for BufferBackend interface."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
from pathlib import Path
import uuid

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_buffer.models import BufferEntry
from mcp_buffer.backend import BufferBackend, BufferBackendError


class MockBufferBackend(BufferBackend):
    """A simple in-memory implementation for testing."""

    def __init__(self):
        self._entries: dict[str, BufferEntry] = {}

    async def create_entry(self, entry: BufferEntry) -> BufferEntry:
        self._entries[entry.id] = entry
        return entry

    async def get_entry(self, entry_id: str) -> BufferEntry | None:
        return self._entries.get(entry_id)

    async def update_entry(self, entry: BufferEntry) -> BufferEntry:
        if entry.id not in self._entries:
            raise BufferBackendError(f"Entry {entry.id} not found")
        self._entries[entry.id] = entry
        return entry

    async def delete_entry(self, entry_id: str) -> bool:
        if entry_id in self._entries:
            del self._entries[entry_id]
            return True
        return False

    async def list_entries(self) -> list[BufferEntry]:
        return sorted(
            self._entries.values(),
            key=lambda e: e.created_at,
            reverse=True
        )


@pytest.fixture
def backend() -> MockBufferBackend:
    """Create a mock backend for testing."""
    return MockBufferBackend()


class TestBufferEntry:
    """Tests for the BufferEntry model."""

    def test_buffer_entry_creation(self):
        """Test creating a buffer entry with required fields."""
        entry = BufferEntry(
            id="test-123",
            content="Hello, world!"
        )
        assert entry.id == "test-123"
        assert entry.content == "Hello, world!"
        assert isinstance(entry.created_at, datetime)
        assert isinstance(entry.updated_at, datetime)
        assert entry.metadata == {}

    def test_buffer_entry_update(self):
        """Test that update() refreshes the timestamp."""
        initial_time = datetime(2024, 1, 1, 12, 0, 0)
        entry = BufferEntry(
            id="test-123",
            content="Hello, world!",
            created_at=initial_time,
            updated_at=initial_time
        )

        # Simulate time passing and update
        with patch("mcp_buffer.models.datetime") as mock_datetime:
            mock_datetime.utcnow.return_value = datetime(2024, 1, 1, 13, 0, 0)
            entry.update()

        assert entry.updated_at != initial_time


class TestBufferBackendInterface:
    """Tests for the BufferBackend interface behavior."""

    @pytest.mark.asyncio
    async def test_create_entry(self, backend: MockBufferBackend):
        """Test creating a new buffer entry."""
        entry = BufferEntry(
            id="test-1",
            content="First entry"
        )
        result = await backend.create_entry(entry)

        assert result.id == "test-1"
        assert result.content == "First entry"
        assert result in (await backend.list_entries())

    @pytest.mark.asyncio
    async def test_get_existing_entry(self, backend: MockBufferBackend):
        """Test retrieving an existing entry."""
        entry = BufferEntry(id="test-2", content="Second entry")
        await backend.create_entry(entry)

        result = await backend.get_entry("test-2")
        assert result is not None
        assert result.content == "Second entry"

    @pytest.mark.asyncio
    async def test_get_nonexistent_entry(self, backend: MockBufferBackend):
        """Test retrieving a non-existent entry returns None."""
        result = await backend.get_entry("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_existing_entry(self, backend: MockBufferBackend):
        """Test updating an existing entry."""
        entry = BufferEntry(id="test-3", content="Original content")
        await backend.create_entry(entry)

        updated = BufferEntry(
            id="test-3",
            content="Updated content",
            created_at=entry.created_at,
            updated_at=entry.updated_at
        )
        result = await backend.update_entry(updated)

        assert result.content == "Updated content"

    @pytest.mark.asyncio
    async def test_delete_existing_entry(self, backend: MockBufferBackend):
        """Test deleting an existing entry."""
        entry = BufferEntry(id="test-4", content="To be deleted")
        await backend.create_entry(entry)

        result = await backend.delete_entry("test-4")
        assert result is True
        assert await backend.get_entry("test-4") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_entry(self, backend: MockBufferBackend):
        """Test deleting a non-existent entry returns False."""
        result = await backend.delete_entry("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_list_entries_empty(self, backend: MockBufferBackend):
        """Test listing entries when empty."""
        entries = await backend.list_entries()
        assert len(entries) == 0

    @pytest.mark.asyncio
    async def test_list_entries_sorted_newest_first(self, backend: MockBufferBackend):
        """Test that list_entries returns entries sorted by creation time (newest first)."""
        entry1 = BufferEntry(id="first", content="First")
        entry2 = BufferEntry(id="second", content="Second")

        # Create with explicit timestamps to control ordering
        from unittest.mock import patch
        with patch("mcp_buffer.models.datetime") as mock_datetime:
            mock_datetime.utcnow.return_value = datetime(2024, 1, 1)
            await backend.create_entry(entry1)
            mock_datetime.utcnow.return_value = datetime(2024, 1, 2)
            await backend.create_entry(entry2)

        entries = await backend.list_entries()
        assert len(entries) == 2
        assert entries[0].id == "second"  # Newest first


class TestBufferBackendError:
    """Tests for BufferBackendError exception."""

    def test_buffer_backend_error_message(self):
        """Test that the error message is preserved."""
        msg = "Connection failed"
        error = BufferBackendError(msg)
        assert str(error) == msg
