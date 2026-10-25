"""Recording deletion preserves response history and invalidates late transcription results."""

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app import call_worker
from app.call_audio import audio_path
from app.call_delete import DeleteCall, mark_call_deleted
from app.db import now
from app.models import AgentRun, Call, CoordinatorAction, Report, ResponsePlan, User
from app.response_seed import reset_response_demo
from app.sample_calls import SAMPLES
from app.transcription import TranscriptResult
from call_helpers import COORDINATOR, submit_call


def upload(client):
    """Upload real fixture bytes as an ordinary user recording, without transcribing them."""
    response = client.post('/calls', headers=COORDINATOR, files={
        'audio': ('recording.wav', SAMPLES['collision'].audio_path.read_bytes(), 'audio/wav'),
    })
    assert response.status_code == 201
    return response.json()


@pytest.mark.parametrize('status', ['queued', 'transcribing', 'awaiting_review', 'failed'])
def test_delete_uploaded_recording(system, status):
    """Deleting the observed version removes audio, private text and its queue entry only."""
    client, factory = system
    call = upload(client)
    other = upload(client)
    with factory() as db:
        record = db.get(Call, call['id'])
        record.status = status
        record.claim_token = 'old-claim'
        record.lease_expires_at = now() + timedelta(minutes=1)
        db.commit()
        version, path = record.version, audio_path(record.audio_key)
    url = f"/calls/{call['id']}"
    stale = client.request('DELETE', url, headers=COORDINATOR, json={'version': version + 1})
    assert stale.status_code == 409 and path.exists()
    result = client.request('DELETE', url, headers=COORDINATOR, json={'version': version})
    assert result.status_code == 200 and not result.json()['cleanup_pending']
    assert not path.exists()
    assert client.get(url, headers=COORDINATOR).status_code == 404
    assert client.get(f'{url}/audio', headers=COORDINATOR).status_code == 404
    assert [item['id'] for item in client.get('/calls', headers=COORDINATOR).json()] == [other['id']]
    assert client.request('DELETE', url, headers=COORDINATOR, json={'version': version}).status_code == 404
    with factory() as db:
        assert db.get(Call, call['id']) is None
        audit = db.scalar(select(CoordinatorAction).where(CoordinatorAction.action == 'call_delete'))
        assert call['id'] in audit.details
        assert record.audio_key not in audit.details


def test_delete_confirmed_recording_preserves_workflow(system):
    """Reports, agent jobs and response plans survive recording deletion unchanged."""
    client, factory = system
    call = submit_call(client).json()
    with factory() as db:
        report_text = db.get(Report, call['report_id']).description
        run_ids = list(db.scalars(select(AgentRun.id)))
        plan_status = db.get(ResponsePlan, call['plan_id']).status
    result = client.request('DELETE', f"/calls/{call['id']}", headers=COORDINATOR,
                            json={'version': call['version']})
    assert result.status_code == 200
    with factory() as db:
        assert db.get(Report, call['report_id']).description == report_text
        assert list(db.scalars(select(AgentRun.id))) == run_ids
        assert db.get(ResponsePlan, call['plan_id']).status == plan_status
    assert client.get(f"/response-plans/{call['plan_id']}", headers=COORDINATOR).json()['call'] is None


def test_cleanup_failure_is_hidden_and_retried_after_reset(system, monkeypatch):
    """A filesystem failure leaves a durable inaccessible tombstone that reset cannot resurrect."""
    client, factory = system
    call = upload(client)
    original = Path.unlink

    def unavailable(path, *args, **kwargs):
        """Simulate a storage outage while retaining the real file for the retry."""
        raise PermissionError('storage unavailable')

    monkeypatch.setattr(Path, 'unlink', unavailable)
    response = client.request('DELETE', f"/calls/{call['id']}", headers=COORDINATOR,
                              json={'version': call['version']})
    assert response.status_code == 200 and response.json()['cleanup_pending']
    assert client.get('/calls', headers=COORDINATOR).json() == []
    for suffix in ['', '/audio']:
        assert client.get(f"/calls/{call['id']}{suffix}", headers=COORDINATOR).status_code == 404
    with factory() as db:
        user = db.scalar(select(User).where(User.role == 'coordinator'))
        reset_response_demo(db, user)
        db.commit()
        assert db.get(Call, call['id']).status == 'deleted'
        path = audio_path(db.get(Call, call['id']).audio_key)
        assert path.exists()
    monkeypatch.setattr(Path, 'unlink', original)
    assert not call_worker.process_one_call()
    with factory() as db:
        assert db.get(Call, call['id']) is None
    assert not path.exists()


def test_deletion_during_transcription_discards_late_result(system, monkeypatch):
    """An in-flight provider cannot restore a call after a dispatcher deletes it."""
    client, factory = system
    call = upload(client)

    class Adapter:
        """Delete the recording after its worker claim, before returning a transcript."""

        def transcribe(self, *args):
            """Model a result arriving after deletion was durably committed."""
            current = client.get(f"/calls/{call['id']}", headers=COORDINATOR).json()
            response = client.request('DELETE', f"/calls/{call['id']}", headers=COORDINATOR,
                                      json={'version': current['version']})
            assert response.status_code == 200
            return TranscriptResult(text=SAMPLES['collision'].transcript)

    monkeypatch.setattr(call_worker, 'get_transcription_adapter', Adapter)
    assert call_worker.process_one_call()
    with factory() as db:
        assert db.get(Call, call['id']) is None


def test_uncommitted_deletion_does_not_remove_audio(system):
    """Rolling back a deletion transaction retains the recording and its queue state."""
    client, factory = system
    call = upload(client)
    with factory() as db:
        user = db.scalar(select(User).where(User.role == 'coordinator'))
        path = audio_path(db.get(Call, call['id']).audio_key)
        mark_call_deleted(db, call['id'], user, DeleteCall(version=call['version']))
        db.rollback()
        assert db.get(Call, call['id']).status == 'queued'
        assert path.exists()
        assert not db.scalar(select(CoordinatorAction.id).where(CoordinatorAction.action == 'call_delete'))
