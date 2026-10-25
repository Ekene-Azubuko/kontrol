"""Drive existing regression scenarios through the dispatcher call boundary."""

from app import call_worker

COORDINATOR = {"Authorization": "Bearer demo-coordinator"}


def submit_call(client, data=None):
    """Inject, transcribe and review a sample, optionally substituting a regression transcript."""
    call = client.post("/calls/sample/collision", headers=COORDINATOR)
    assert call.status_code == 201, call.text
    assert call_worker.process_one_call()
    call = client.get(f"/calls/{call.json()['id']}", headers=COORDINATOR).json()
    data = data or {}
    transcript = data.get("description", call["original_transcript"])
    if "reported_casualties" in data and data["reported_casualties"] is not None:
        transcript = (
            f"SIMULATION: Vehicles collided; {data['reported_casualties']} people reported injured. "
            + transcript
        )
    return client.post(
        f"/calls/{call['id']}/confirm-review",
        headers=COORDINATOR,
        json={
            "transcript": transcript,
            "category": data.get("category", "collision"),
            "latitude": data.get("latitude", 37.777),
            "longitude": data.get("longitude", -122.414),
            "address": data.get("location", "Market & 8th exercise area"),
            "version": call["version"],
        },
    )
