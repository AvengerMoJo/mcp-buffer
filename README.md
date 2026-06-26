# mcp-buffer

Personal cloud storage buffer layer for MCP — upload large content to Google Drive/Dropbox and pass URLs to agents.

## Install

```bash
pip install mcp-buffer
```

## Quick start

```python
from mcp_buffer.tools import buffer_upload_file, buffer_expire

result = await buffer_upload_file(content="Hello", filename="note.txt")
print(result["link"])
await buffer_expire(result["buffer_id"])
```

## Backends

- **Google Drive** (Phase 1) — 15GB free, NotebookLM native
- **Dropbox** (Phase 2) — coming soon
