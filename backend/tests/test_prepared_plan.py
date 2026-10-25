"""Check prepared queue placement, approval persistence and idempotent loading."""

from sqlalchemy import func, select
from app.models import AgentRun, CommunicationLog, DispatchAssignment, Hospital, ResponsePlan
from app.prepared_plan import load_prepared_plan
from app.seed import seed
from test_workflow import COORDINATOR


def test_prepared_plan_stays_visible_after_approval_and_reload(system):
    """The saved example enters review, approves through the real API and never resets on reload."""
    client, factory = system
    with factory() as db:
        seed(db)
        plan = load_prepared_plan(db)
        plan_id = plan.id
        db.commit()
        assert load_prepared_plan(db).id == plan_id
        db.commit()
    plans = client.get('/response-plans', headers=COORDINATOR).json()
    assert len(plans) == 1 and plans[0]['status'] == 'awaiting_approval'
    plan = plans[0]
    assert len(plan['runs']) == 4 and all(r['status'] == 'completed' and r['remote_id'] is None for r in plan['runs'])
    assert {a['vehicle']['call_sign'] for a in plan['assignments']} == {'AMB-01', 'POL-01'}
    approved = client.post(f'/response-plans/{plan_id}/decision', headers=COORDINATOR,
                          json={'action': 'approve', 'version': plan['version'], 'note': 'Reviewed prepared judging scenario'})
    assert approved.status_code == 200, approved.text
    assert approved.json()['status'] == 'approved'
    assert client.get('/response-plans', headers=COORDINATOR).json()[0]['status'] == 'approved'
    assert len(client.get('/dispatches', headers=COORDINATOR).json()) == 2
    with factory() as db:
        assert load_prepared_plan(db).status == 'approved'
        assert db.scalar(select(func.count()).select_from(ResponsePlan)) == 1
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 4
        assert not db.scalar(select(CommunicationLog))
        assert all(a.status == 'assigned' and not a.completed_at and a.reserved_beds == 0 for a in db.scalars(select(DispatchAssignment)))
        assert all(h.total_beds is None for h in db.scalars(select(Hospital).where(Hospital.discovered_by_agent.is_(True))))
