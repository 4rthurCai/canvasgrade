"""The GUI's JSON API.

These never reach Canvas: the endpoints that would are covered by the workflow tests.
What matters here is that uploads are parsed, errors come back as JSON rather than a
traceback, and the credential never leaves the server.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from canvasgrade.config import Profile
from canvasgrade.web.app import create_app
from canvasgrade.web.state import UploadError, UploadStore

pytestmark = pytest.mark.integration

SECRET = "super-secret-canvas-token"


@pytest.fixture
def client():
    app = create_app(Profile(api_url="https://canvas.example.invalid/", api_key=SECRET))
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def uploaded(client, gradebook_path):
    with gradebook_path.open("rb") as handle:
        response = client.post("/api/uploads", files={"file": ("gradebook.csv", handle, "text/csv")})
    assert response.status_code == 200
    return response.json()


def test_the_page_and_its_assets_are_served(client) -> None:
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200


class TestUpload:
    def test_detection_results_reach_the_browser(self, uploaded) -> None:
        assert uploaded["students"] == 4
        assert uploaded["teams"] == ["teamalpha", "teambeta"]
        criteria = [c for c in uploaded["columns"] if c["role"] == "criterion"]
        assert len(criteria) == 4
        assert sum(c["points"] for c in criteria) == 60

    def test_every_column_carries_its_reason(self, uploaded) -> None:
        assert all(column["reason"] for column in uploaded["columns"])

    def test_a_preview_of_the_raw_rows_is_included(self, uploaded) -> None:
        assert len(uploaded["preview"]) > 0

    def test_an_empty_file_is_a_400_not_a_500(self, client) -> None:
        response = client.post("/api/uploads", files={"file": ("empty.csv", b"", "text/csv")})
        assert response.status_code == 400
        assert "empty" in response.json()["detail"]

    def test_an_unreadable_file_is_a_400(self, client) -> None:
        response = client.post("/api/uploads", files={"file": ("notes.docx", b"junk", "application/msword")})
        assert response.status_code == 400


class TestErrors:
    def test_an_unknown_upload_token_is_a_400(self, client) -> None:
        response = client.post("/api/plan", json={"token": "made-up", "course_id": 1, "assignment_id": 2})
        assert response.status_code == 400
        assert "expired" in response.json()["detail"]

    def test_an_unreachable_canvas_is_a_400_with_advice(self, client) -> None:
        response = client.get("/api/session")
        assert response.status_code == 400
        assert "canvas" in response.json()["detail"].lower()


def test_the_access_token_is_never_sent_to_the_browser(client, uploaded) -> None:
    for path in ("/", "/static/app.js", "/static/index.html"):
        assert SECRET not in client.get(path).text
    assert SECRET not in str(uploaded)


class TestUploadStore:
    def test_files_land_outside_the_project(self, tmp_path) -> None:
        store = UploadStore(tmp_path / "uploads")
        upload = store.add("grades.csv", b"a,b\n1,2\n")
        assert upload.path.exists()
        assert upload.path.is_relative_to(tmp_path)
        store.close()
        assert not upload.path.exists()

    def test_oversized_uploads_are_refused(self, tmp_path) -> None:
        store = UploadStore(tmp_path / "uploads")
        with pytest.raises(UploadError, match="larger than"):
            store.add("huge.csv", b"x" * (33 * 1024 * 1024))
        store.close()

    def test_the_stored_name_cannot_escape_the_directory(self, tmp_path) -> None:
        store = UploadStore(tmp_path / "uploads")
        upload = store.add("../../etc/passwd.csv", b"a\n1\n")
        assert upload.path.parent == store.root
        store.close()
