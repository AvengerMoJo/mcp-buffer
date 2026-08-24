# mcp-buffer

A file-handoff buffer layer for MCP agents. When an agent has a file it
can't process locally — too large, wrong format, needs a backend that can
decode it — it pushes the file into the buffer and gets back a URL a
consumer can GET/stream, instead of trying to cram the bytes through a
JSON-RPC tool call.

## Install

```bash
pip install -e .
```

## Quick start (as an MCP server)

```bash
python -m mcp_buffer.server --transport stdio
```

Exposes 4 tools: `buffer_upload_file(path, filename?, mime_type?, ttl_seconds?, folder_id?)`,
`buffer_get_link(buffer_id)`, `buffer_list(folder_id?)`, `buffer_expire(buffer_id)`.

## Pastebin-style HTTP upload (remote callers)

`buffer_upload_file` reads a *path* from the buffer host's disk, so it only
works when the caller shares a filesystem with the server. Any remote
caller pushes raw bytes instead and gets a public link back:

```bash
curl -X PUT 'https://buffer.example.com/buffer/upload?filename=report.pdf' \
     -H 'Content-Type: application/pdf' \
     --data-binary @report.pdf
# -> {"buffer_id": "...", "link": "https://buffer.example.com/<id>",
#     "filename": "report.pdf", "mime_type": "application/pdf",
#     "size_bytes": 12345, "expires_at": null}
```

Then hand `link` to any consumer (another agent, a backend service,
NotebookLM) that downloads it for local processing — no base64 through
JSON-RPC, no shared filesystem required. `POST` also works; query params:
`filename`, `mime_type`, `ttl_seconds`, `folder_id`.

## Quick start (as a library)

```python
from mcp_buffer.local_backend import LocalFileBackend

backend = LocalFileBackend()
entry = await backend.buffer_upload("/path/to/report.pdf", filename="report.pdf")
print(entry.link)          # http://127.0.0.1:PORT/<buffer_id> -- streams with Range support
await backend.expire(entry.buffer_id)
```

## Backends

- **local** (default, ships today) — stores files on disk under
  `MCP_BUFFER_LOCAL_DIR` (default `~/.mcp-buffer/store`), serves them back
  over a lazily-started local HTTP server with byte-range support. No
  cloud auth required — this is also the reference implementation every
  other backend should match.
- **Google Drive / OneDrive / S3 / Nextcloud** — not implemented yet.
  Add one by subclassing `BufferBackend` (`mcp_buffer/backend.py`) and
  registering it:

  ```python
  from mcp_buffer.registry import BufferRegistry
  from mcp_buffer.backend import BufferBackend

  @BufferRegistry.register("gdrive")
  class GoogleDriveBackend(BufferBackend):
      async def buffer_upload(self, content, filename, mime_type=None,
                               ttl_seconds=None, folder_id=None): ...
      async def get_link(self, buffer_id): ...
      async def expire(self, buffer_id): ...
      async def list(self, folder_id=None): ...
      async def can_reuse(self, buffer_id): ...
  ```

  Select it with `MCP_BUFFER_BACKEND=gdrive` (see `server.py`). Every
  backend returns the same shape (`BufferEntry`: `buffer_id`, `link`,
  `filename`, `mime_type`, `size_bytes`, `expires_at`, ...) so callers
  never need backend-specific logic.

## Running behind a public domain (e.g. Cloudflare Tunnel)

By default the local server binds loopback-only on a random port, and
links point at `http://127.0.0.1:<port>` — fine for same-host use, useless
to any external consumer (NotebookLM, an OCR service, a remote agent).
Three env vars make it reachable from a real domain without touching the
loopback bind (a tunnel like `cloudflared` connects to the local port
directly, so `127.0.0.1` is still correct/safer as the bind address):

```bash
export MCP_BUFFER_HTTP_HOST=127.0.0.1      # what the server binds
export MCP_BUFFER_HTTP_PORT=8600           # fixed port a tunnel config can target
export MCP_BUFFER_PUBLIC_URL=https://buffer.example.com  # what links use instead of 127.0.0.1:PORT
```

Then point one `cloudflared` ingress rule at the fixed port:

```yaml
- hostname: buffer.example.com
  service: http://127.0.0.1:8600
```

If your zone already has a wildcard DNS record (`*.example.com` CNAME to
the tunnel), no new DNS record is needed — the ingress rule alone routes
that hostname to this service.

## Design notes

- `content` passed to `buffer_upload` may be a local filesystem path (the
  common case — an agent already has the file on disk) or raw bytes.
- TTL (`ttl_seconds`) is enforced lazily on access (`get_link`/`can_reuse`)
  and swept on `list()` — no background job required.
- The local backend's HTTP server is a single stdlib `ThreadingHTTPServer`
  shared process-wide across every `LocalFileBackend` instance (even ones
  pointed at different `store_dir`s); files are looked up by `buffer_id`
  through a shared in-process table, not bound to whichever backend
  instance happened to start the server first.
