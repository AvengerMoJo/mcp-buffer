"""Google Drive buffer backend implementation."""

import json
import os
from datetime import datetime
from typing import Optional, Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .backend import BufferBackend, BufferBackendError
from .models import BufferEntry


class GoogleDriveBuffer(BufferBackend):
    """A buffer backend that stores entries in Google Drive.

    This implementation uses a single Google Sheet as the backing store for
    all buffer entries. Each row represents one entry with columns for id,
    content, created_at, updated_at, and metadata (as JSON).
    """

    SHEET_ID_ENV_VAR = "MCP_BUFFER_DRIVE_SHEET_ID"
    CREDENTIALS_PATH = os.environ.get(
        "GOOGLE_APPLICATION_CREDENTIALS", "~/.config/mcp-buffer/credentials.json"
    )

    def __init__(self, sheet_id: Optional[str] = None):
        """Initialize the Google Drive buffer backend.

        Args:
            sheet_id: The Google Sheet ID to use as storage. If not provided,
                     will be read from MCP_BUFFER_DRIVE_SHEET_ID environment variable.
        """
        self._sheet_id = sheet_id or os.environ.get(self.SHEET_ID_ENV_VAR)
        if not self._sheet_id:
            raise ValueError(
                f"Sheet ID must be provided or set as {self.SHEET_ID_ENV_VAR} env var"
            )

        self._service: Optional[Any] = None
        self._sheet_metadata: Optional[dict] = None

    def _get_service(self) -> Any:
        """Get or create the Sheets API service.

        Returns:
            The Google Sheets API service instance.

        Raises:
            BufferBackendError: If authentication fails.
        """
        if self._service is not None:
            return self._service

        try:
            from google.oauth2 import service_account
            credentials = service_account.Credentials.from_service_account_file(
                os.path.expanduser(self.CREDENTIALS_PATH)
            )
            self._service = build("sheets", "v4", credentials=credentials)
            return self._service
        except ImportError as e:
            raise BufferBackendError(f"Missing dependency: {e}")
        except Exception as e:
            raise BufferBackendError(f"Failed to authenticate with Google Sheets: {e}")

    def _get_sheet_metadata(self) -> dict:
        """Fetch and cache the spreadsheet metadata (includes sheet IDs).

        Returns:
            The full spreadsheets.get response.

        Raises:
            BufferBackendError: If fetching metadata fails.
        """
        if self._sheet_metadata is not None:
            return self._sheet_metadata

        service = self._get_service()
        try:
            self._sheet_metadata = (
                service.spreadsheets()
                .get(spreadsheetId=self._sheet_id)
                .execute()
            )
            return self._sheet_metadata
        except HttpError as e:
            raise BufferBackendError(f"Failed to get spreadsheet metadata: {e}")

    def _find_row_for_entry(self, entry_id: str) -> Optional[int]:
        """Find the row number (1-indexed) for a given entry ID.

        Returns:
            Row number (starting from 2, since row 1 is the header), or None if not found.
        """
        service = self._get_service()

        try:
            result = (
                service.spreadsheets()
                .values()
                .get(spreadsheetId=self._sheet_id, range="Sheet1!A:A")
                .execute()
            )
        except HttpError as e:
            raise BufferBackendError(f"Failed to find entry row: {e}")

        values = result.get("values", [])
        for idx, row in enumerate(values[1:], start=2):  # Skip header, rows start at 2
            if row and row[0] == entry_id:
                return idx
        return None

    async def create_entry(self, entry: BufferEntry) -> BufferEntry:
        """Create a new buffer entry in Google Drive.

        Args:
            entry: The buffer entry to create.

        Returns:
            The created entry.

        Raises:
            BufferBackendError: If creation fails.
        """
        service = self._get_service()
        values = [
            [entry.id, entry.content, entry.created_at.isoformat(),
             entry.updated_at.isoformat(), json.dumps(entry.metadata)]
        ]

        try:
            (
                service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self._sheet_id,
                    range="Sheet1!A:E",
                    valueInputOption="USER_ENTERED",
                    body={"values": values}
                )
                .execute()
            )
        except HttpError as e:
            raise BufferBackendError(f"Failed to create entry: {e}")

        return entry

    async def get_entry(self, entry_id: str) -> Optional[BufferEntry]:
        """Retrieve a buffer entry by ID from Google Drive.

        Args:
            entry_id: The unique identifier of the entry.

        Returns:
            The requested entry, or None if not found.

        Raises:
            BufferBackendError: If retrieval fails for non-technical reasons.
        """
        service = self._get_service()

        try:
            result = (
                service.spreadsheets()
                .values()
                .get(spreadsheetId=self._sheet_id, range="Sheet1!A:E")
                .execute()
            )
        except HttpError as e:
            raise BufferBackendError(f"Failed to get entry: {e}")

        values = result.get("values", [])
        if len(values) <= 1:  # Only header row exists
            return None

        for row in values[1:]:
            if row and row[0] == entry_id:
                try:
                    return BufferEntry(
                        id=row[0],
                        content=row[1] or "",
                        created_at=datetime.fromisoformat(row[2]),
                        updated_at=datetime.fromisoformat(row[3]),
                        metadata=json.loads(row[4]) if row[4] else {}
                    )
                except (ValueError, KeyError) as e:
                    raise BufferBackendError(f"Failed to parse entry: {e}")

        return None

    async def update_entry(self, entry: BufferEntry) -> BufferEntry:
        """Update an existing buffer entry in Google Drive.

        Args:
            entry: The buffer entry with updated content.

        Returns:
            The updated entry.

        Raises:
            BufferBackendError: If the entry doesn't exist or update fails.
        """
        service = self._get_service()
        values = [
            [entry.id, entry.content, entry.created_at.isoformat(),
             entry.updated_at.isoformat(), json.dumps(entry.metadata)]
        ]

        # Find the row index for this entry (skip header)
        row_index = self._find_row_for_entry(entry.id)
        if row_index is None:
            raise BufferBackendError(f"Entry {entry.id} not found")

        try:
            service.spreadsheets().batchUpdate(
                spreadsheetId=self._sheet_id,
                body={
                    "requests": [
                        {
                            "updateCells": {
                                "rows": [
                                    {
                                        "values": [
                                            {"userEnteredValue": {"stringValue": entry.id}},
                                            {"userEnteredValue": {"stringValue": entry.content}},
                                            {"userEnteredValue": {"stringValue": entry.created_at.isoformat()}},
                                            {"userEnteredValue": {"stringValue": entry.updated_at.isoformat()}},
                                            {"userEnteredValue": {"stringValue": json.dumps(entry.metadata)}},
                                        ]
                                    }
                                ],
                                "fields": "userEnteredValue",
                                "start": {
                                    "sheetId": self._get_sheet_metadata()["sheets"][0]["properties"]["sheetId"],
                                    "rowIndex": row_index - 1,
                                    "columnIndex": 0
                                }
                            }
                        }
                    ]
                }
            ).execute()
        except HttpError as e:
            raise BufferBackendError(f"Failed to update entry: {e}")

        return entry

    async def delete_entry(self, entry_id: str) -> bool:
        """Delete a buffer entry from Google Drive.

        Args:
            entry_id: The unique identifier of the entry to delete.

        Returns:
            True if deleted, False if not found.

        Raises:
            BufferBackendError: If deletion fails for non-technical reasons.
        """
        service = self._get_service()

        # Find the row number
        delete_row = self._find_row_for_entry(entry_id)

        if delete_row is None:
            return False

        try:
            service.spreadsheets().batchUpdate(
                spreadsheetId=self._sheet_id,
                body={
                    "requests": [
                        {
                            "deleteDimension": {
                                "range": {
                                    "sheetId": self._get_sheet_metadata()["sheets"][0]["properties"]["sheetId"],
                                    "dimension": "ROWS",
                                    "startIndex": delete_row - 1,
                                    "endIndex": delete_row
                                }
                            }
                        }
                    ]
                }
            ).execute()
        except HttpError as e:
            raise BufferBackendError(f"Failed to delete entry: {e}")

        return True

    async def list_entries(self) -> list[BufferEntry]:
        """List all buffer entries from Google Drive.

        Returns:
            A list of all buffer entries, ordered by creation time (newest first).

        Raises:
            BufferBackendError: If listing fails for non-technical reasons.
        """
        service = self._get_service()
        entries: list[BufferEntry] = []

        try:
            result = (
                service.spreadsheets()
                .values()
                .get(spreadsheetId=self._sheet_id, range="Sheet1!A:E")
                .execute()
            )
        except HttpError as e:
            raise BufferBackendError(f"Failed to list entries: {e}")

        values = result.get("values", [])
        if len(values) <= 1:
            return entries

        for row in values[1:]:
            try:
                entry = BufferEntry(
                    id=row[0],
                    content=row[1] or "",
                    created_at=datetime.fromisoformat(row[2]),
                    updated_at=datetime.fromisoformat(row[3]),
                    metadata=json.loads(row[4]) if row[4] else {}
                )
                entries.append(entry)
            except (ValueError, KeyError):
                continue

        return sorted(entries, key=lambda e: e.created_at, reverse=True)


