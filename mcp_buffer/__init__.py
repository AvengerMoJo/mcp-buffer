"""mcp-buffer: a file-handoff buffer layer for MCP agents.

Push a file too large or too binary for a JSON-RPC tool call into a
buffer; get back a link a backend can GET/stream instead. Pluggable
storage backends share one contract (backend.py) via BufferRegistry.
"""

from .models import BufferEntry
from .backend import BufferBackend, BufferBackendError
from .registry import BufferRegistry
from .local_backend import LocalFileBackend

__all__ = [
    "BufferEntry",
    "BufferBackend",
    "BufferBackendError",
    "BufferRegistry",
    "LocalFileBackend",
]

__version__ = "0.2.0"
