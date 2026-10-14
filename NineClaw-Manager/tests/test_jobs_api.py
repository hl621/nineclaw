"""Job API smoke tests."""

from __future__ import annotations

import pytest

from app.jobs.broker import broker
from app.jobs.registry import register_job_handler
from app.jobs.service import job_service


@pytest.mark.asyncio
async def test_job_service_records_events() -> None:
    job = await job_service.create_job(job_type="test.manual", payload={"x": 1})
    await job_service.mark_running(job.id)
    await job_service.mark_succeeded(job.id, result={"ok": True})

    saved = await job_service.get_job(job.id)
    events = await job_service.list_events(job.id)

    assert saved.status == "succeeded"
    assert saved.result == {"ok": True}
    assert [event.type for event in events] == ["queued", "running", "succeeded"]


@pytest.mark.asyncio
async def test_jobs_route_enqueues_registered_task(client) -> None:
    job_type = "test.route"

    async def handler(job):
        await job_service.emit(job.id, "custom", "handler ran", progress=50)
        return {"job_id": job.id}

    register_job_handler(job_type, handler)

    await broker.startup()
    try:
        resp = await client.post(
            "/v1/jobs",
            json={"type": job_type, "payload": {"hello": "world"}},
        )
        assert resp.status_code == 202, resp.text
        job_id = resp.json()["job"]["id"]
        await broker.wait_all()
    finally:
        await broker.shutdown()

    job_resp = await client.get(f"/v1/jobs/{job_id}")
    assert job_resp.status_code == 200
    assert job_resp.json()["job"]["status"] == "succeeded"

    events_resp = await client.get(f"/v1/jobs/{job_id}/events")
    assert events_resp.status_code == 200
    event_types = [event["type"] for event in events_resp.json()["items"]]
    assert event_types == ["queued", "running", "custom", "succeeded"]
