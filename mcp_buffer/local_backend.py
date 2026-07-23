"""LocalFileBackend — filesystem-backed BufferBackend, no cloud auth needed.

Stores uploaded files under MCP_BUFFER_LOCAL_DIR (default
~/.mcp-buffer/store), tracks metadata in a JSON index alongside them, and
serves them back over a lazily-started local HTTP server (http_server.py)
with Range support so a downstream consumer can stream/seek large files
instead of round-tripping them through JSON-RPC.

This is the reference implementation other backends (Drive/OneDrive/S3/
Nextcloud) should match: same BufferBackend contract, same link shape
(a URL a GET request can stream from), swapped storage/transport only.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Union

from . import http_server
from .backend import BufferBackend, BufferBackendError
from .http_server import BufferHTTPServer
from .models import BufferEntry
from .registry import BufferRegistry

_DIR_ENV_VAR = "MCP_BUFFER_LOCAL_DIR"


@BufferRegistry.register("local")
class LocalFileBackend(BufferBackend):
    def __init__(self, store_dir: Optional[str] = None):
        self._store_dir = Path(
            store_dir or os.environ.get(_DIR_ENV_VAR) or Path.home() / ".mcp-buffer" / "store"
        )
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._store_dir / "_index.json"
        self._entries: dict[str, BufferEntry] = self._load_index()
        self._server = BufferHTTPServer.shared()
        self._register_active_entries_with_server()

    # ------------------------------------------------------------------
    # BufferBackend contract
    # ------------------------------------------------------------------

    async def buffer_upload(
        self,
        content: Union[str, bytes],
        filename: str,
        mime_type: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
        folder_id: Optional[str] = None,
    ) -> BufferEntry:
        buffer_id = str(uuid.uuid4())
        dest = self._store_dir / buffer_id
        resolved_mime = mime_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"

        await asyncio.to_thread(self._write_content, content, dest)

        expires_at = None
        if ttl_seconds is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)

        entry = BufferEntry(
            buffer_id=buffer_id,
            provider="local",
            filename=filename,
            mime_type=resolved_mime,
            link=f"{self._server.base_url()}/{buffer_id}",
            size_bytes=dest.stat().st_size,
            expires_at=expires_at,
            folder_id=folder_id,
        )
        self._entries[buffer_id] = entry
        self._save_index()
        http_server.register(buffer_id, str(dest), resolved_mime)
        return entry

    async def get_link(self, buffer_id: str) -> str:
        entry = self._active_entry(buffer_id)
        return entry.link

    async def expire(self, buffer_id: str) -> None:
        entry = self._entries.get(buffer_id)
        if entry is None:
            raise BufferBackendError(f"Unknown buffer_id '{buffer_id}'")
        entry.status = "expired"
        self._save_index()
        http_server.unregister(buffer_id)
        dest = self._store_dir / buffer_id
        if dest.is_file():
            await asyncio.to_thread(dest.unlink)

    async def list(self, folder_id: Optional[str] = None) -> list[BufferEntry]:
        self._sweep_expired()
        entries = [
            e for e in self._entries.values()
            if e.status == "active" and (folder_id is None or e.folder_id == folder_id)
        ]
        return sorted(entries, key=lambda e: e.created_at, reverse=True)

    async def can_reuse(self, buffer_id: str) -> bool:
        entry = self._entries.get(buffer_id)
        if entry is None or entry.status != "active":
            return False
        if entry.is_expired():
            entry.status = "expired"
            self._save_index()
            http_server.unregister(buffer_id)
            return False
        return True

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _write_content(self, content: Union[str, bytes], dest: Path) -> None:
        if isinstance(content, (bytes, bytearray)):
            dest.write_bytes(bytes(content))
            return
        source = Path(content)
        if source.is_file():
            shutil.copyfile(source, dest)
            return
        dest.write_text(content, encoding="utf-8")

    def _active_entry(self, buffer_id: str) -> BufferEntry:
        entry = self._entries.get(buffer_id)
        if entry is None:
            raise BufferBackendError(f"Unknown buffer_id '{buffer_id}'")
        if entry.is_expired():
            entry.status = "expired"
            self._save_index()
            http_server.unregister(buffer_id)
        if entry.status != "active":
            raise BufferBackendError(f"buffer_id '{buffer_id}' is expired")
        return entry

    def _register_active_entries_with_server(self) -> None:
        """On startup, re-register already-buffered files (from a prior
        process) with the shared server -- it starts with an empty
        in-memory lookup table each run."""
        for buffer_id, entry in self._entries.items():
            if entry.status != "active" or entry.is_expired():
                continue
            path = self._store_dir / buffer_id
            if path.is_file():
                http_server.register(buffer_id, str(path), entry.mime_type)

    def _sweep_expired(self) -> None:
        changed = False
        for buffer_id, entry in self._entries.items():
            if entry.status == "active" and entry.is_expired():
                entry.status = "expired"
                changed = True
                http_server.unregister(buffer_id)
        if changed:
            self._save_index()

    def _load_index(self) -> dict[str, BufferEntry]:
        if not self._index_path.is_file():
            return {}
        try:
            raw = json.loads(self._index_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
        entries: dict[str, BufferEntry] = {}
        for buffer_id, data in raw.items():
            try:
                entries[buffer_id] = BufferEntry.model_validate(data)
            except Exception:
                continue
        return entries

    def _save_index(self) -> None:
        raw = {bid: json.loads(entry.model_dump_json()) for bid, entry in self._entries.items()}
        self._index_path.write_text(json.dumps(raw, indent=2))
