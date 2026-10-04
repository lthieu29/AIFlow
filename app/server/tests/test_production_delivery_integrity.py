"""Storage failures must remain recoverable through the production UI."""

import pytest

from server.tests.test_production import client as client
from server.tests.test_production import portrait, upload


def rendered_portrait(client):
    project = portrait(client)
    upload(client, project, "reference")
    media = upload(client, project, "portrait")
    client.post(f"/api/production/media/{media}/review", json={
        "checklist": ["likeness", "anatomy", "crop", "artifacts"],
    })
    response = client.post(f"/api/production/projects/{project}/render", json={})
    assert response.status_code == 202, response.text
    output = response.json()["output_id"]
    folder = client.root / "production" / "outputs" / str(response.json()["job_id"])
    return output, folder


@pytest.mark.parametrize("action", ["preview", "review"])
def test_missing_imported_file_returns_recoverable_response(client, action):
    from sqlmodel import Session

    from server.db.models.production import ProductionMedia

    project = portrait(client)
    media = upload(client, project, "portrait")
    with Session(client.engine) as db:
        from pathlib import Path
        Path(db.get(ProductionMedia, media).path).unlink()
    if action == "preview":
        response = client.get(f"/api/production/media/{media}")
        assert response.status_code == 404
    else:
        response = client.post(f"/api/production/media/{media}/review", json={
            "checklist": ["likeness", "anatomy", "crop", "artifacts"],
        })
        assert response.status_code == 422


@pytest.mark.parametrize("action", ["preview", "review"])
@pytest.mark.parametrize("change", ["tamper", "remove"])
def test_changed_delivery_cannot_be_previewed_or_approved(client, action, change):
    output, folder = rendered_portrait(client)
    path = folder / "preview.jpg"
    if change == "tamper":
        path.write_bytes(b"changed since render")
    else:
        path.unlink()
    if action == "preview":
        response = client.get(f"/api/production/outputs/{output}/file/preview.jpg")
    else:
        response = client.post(f"/api/production/outputs/{output}/review", json={
            "checklist": ["quality", "rights", "delivery"],
        })
    assert response.status_code == 409, response.text
    assert client.get(f"/api/production/outputs/{output}").json()["status"] == "awaiting_review"


def test_failed_package_removes_partial_archive(client):
    output, folder = rendered_portrait(client)
    client.post(f"/api/production/outputs/{output}/review", json={
        "checklist": ["quality", "rights", "delivery"],
    })
    (folder / "portrait.png").write_bytes(b"tampered")
    response = client.get(f"/api/production/outputs/{output}/download")
    assert response.status_code == 409
    assert not list(folder.glob("delivery-*.tmp"))
