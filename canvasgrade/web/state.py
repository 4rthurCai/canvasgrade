"""In-memory state for the local GUI.

The GUI is a single-user tool bound to loopback, so uploads live in a temporary
directory that is wiped when the server stops. Nothing is written to the project
directory, and no student data outlives the session.
"""

from __future__ import annotations

import secrets
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock

from canvasgrade.errors import CanvasGradeError

#: Uploads older than this are dropped when a new one arrives.
MAX_AGE_SECONDS = 6 * 60 * 60
MAX_UPLOAD_BYTES = 32 * 1024 * 1024


class UploadError(CanvasGradeError):
    """The uploaded file was rejected before it ever reached the parser."""


@dataclass(frozen=True)
class Upload:
    """One spreadsheet the user dropped on the page."""

    token: str
    path: Path
    filename: str
    created_at: float = field(default_factory=time.monotonic)


class UploadStore:
    """A tiny, thread-safe registry of uploaded sheets."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path(tempfile.mkdtemp(prefix="canvasgrade-"))
        self._root.mkdir(parents=True, exist_ok=True)
        self._uploads: dict[str, Upload] = {}
        self._lock = Lock()

    @property
    def root(self) -> Path:
        return self._root

    def add(self, filename: str, content: bytes) -> Upload:
        if not content:
            raise UploadError("The uploaded file is empty.")
        if len(content) > MAX_UPLOAD_BYTES:
            limit = MAX_UPLOAD_BYTES // (1024 * 1024)
            raise UploadError(f"That file is larger than the {limit} MB limit.")

        suffix = Path(filename).suffix.lower()
        token = secrets.token_urlsafe(16)
        path = self._root / f"{token}{suffix}"
        path.write_bytes(content)

        upload = Upload(token=token, path=path, filename=Path(filename).name)
        with self._lock:
            self._uploads[token] = upload
        self._prune()
        return upload

    def get(self, token: str) -> Upload:
        with self._lock:
            upload = self._uploads.get(token)
        if upload is None or not upload.path.exists():
            raise UploadError("That upload has expired. Drop the file on the page again.")
        return upload

    def _prune(self) -> None:
        cutoff = time.monotonic() - MAX_AGE_SECONDS
        with self._lock:
            stale = [token for token, upload in self._uploads.items() if upload.created_at < cutoff]
            for token in stale:
                upload = self._uploads.pop(token)
                upload.path.unlink(missing_ok=True)

    def close(self) -> None:
        """Delete every uploaded file. Called when the server shuts down."""
        with self._lock:
            self._uploads.clear()
        shutil.rmtree(self._root, ignore_errors=True)
