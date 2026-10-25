import asyncio
import io
import json
import time

import httpx
import pytest
from badge_briefing.app import create_app, demo_jpeg
from badge_briefing.config import ROOT, Settings
from badge_briefing.domain import TERMINAL, Classification, Research, State
from badge_briefing.providers import Budget, Ledger, MetaMuseAdapter, MockAdapter
from badge_briefing.quality import gate
from badge_briefing.safety import resolve, safe_url, validate_brief
from PIL import Image


@pytest.fixture
def settings():
    return Settings(
        pin="test-passphrase-only",
        device_token="a" * 43,
        mock_delay=0,
        rate_seconds=0,
        origin="http://testserver",
        job_timeout=2,
    )


@pytest.fixture
async def client(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=settings.origin
        ) as client:
            login = await client.post("/v1/session", json={"pin": settings.pin})
            client.headers["X-CSRF-Token"] = login.json()["csrf"]
            client.app_ref = app
            yield client


async def result(client, job_id):
    for _ in range(200):
        response = await client.get(f"/v1/jobs/{job_id}")
        data = response.json()
        if data.get("state") in TERMINAL:
            return data
        await asyncio.sleep(0.01)
    raise AssertionError("job never completed")


async def demo(client, scenario="success"):
    response = await client.post("/v1/demo", params={"scenario": scenario})
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


async def test_demo_end_to_end_with_sources_and_sse(client):
    job_id = await demo(client)
    data = await result(client, job_id)
    assert data["state"] == "COMPLETE"
    assert data["brief"]["confidence"] == "high"
    assert len(data["brief"]["starters"]) == 3
    ids = {e["id"] for e in data["evidence"]}
    assert all(set(c["source_ids"]) <= ids for c in data["brief"]["starters"])
    stream = await client.get(f"/v1/jobs/{job_id}/events")
    assert "event: progress" in stream.text and "COMPLETE" in stream.text
    assert (await client.get(f"/v1/jobs/{job_id}/brief")).status_code == 200


@pytest.mark.parametrize(
    "scenario,state",
    [
        ("organization", "COMPLETE_ORG_ONLY"),
        ("missing", "COMPLETE_ORG_ONLY"),
        ("rejected", "REJECTED_CARD_TYPE"),
    ],
)
async def test_clean_fallbacks(client, scenario, state):
    data = await result(client, await demo(client, scenario))
    assert data["state"] == state
    if state == "REJECTED_CARD_TYPE":
        assert data["extraction"] is None and data["brief"] is None
    else:
        assert not data["brief"]["interests"]


async def test_capture_dedupe_and_device_compact_status(client, settings):
    headers = {
        "Authorization": "Bearer " + settings.device_token,
        "X-Device-ID": settings.device_id,
        "X-Capture-ID": "capture-retry-001",
        "Content-Type": "image/jpeg",
    }
    first = await client.post("/v1/captures", headers=headers, content=demo_jpeg())
    second = await client.post("/v1/captures", headers=headers, content=demo_jpeg())
    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]
    assert second.json()["duplicate"]
    await result(client, first.json()["job_id"])
    compact = await client.get("/v1/jobs/" + first.json()["job_id"], headers=headers)
    assert "device_lines" in compact.json() and "extraction" not in compact.json()


async def test_simultaneous_retry_creates_only_one_job(client):
    headers = {"X-Capture-ID": "simultaneous-001", "Content-Type": "image/jpeg"}
    payload = demo_jpeg()

    async def slow_body():
        yield payload[:100]
        await asyncio.sleep(0.05)
        yield payload[100:]

    first, second = await asyncio.gather(
        client.post("/v1/captures", headers=headers, content=slow_body()),
        client.post("/v1/captures", headers=headers, content=payload),
    )
    assert first.status_code == second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]
    assert len(client.app_ref.state.pipeline.jobs) == 1


async def test_size_corruption_and_media_type(client):
    h = {"X-Capture-ID": "capture-invalid", "Content-Type": "image/jpeg"}
    assert (await client.post("/v1/captures", headers=h, content=b"a" * 3000001)).status_code == 413
    assert (
        await client.post("/v1/captures", headers={**h, "Content-Type": "image/png"}, content=b"abc")
    ).status_code == 415
    response = await client.post("/v1/captures", headers=h, content=b"\xff\xd8notjpeg\xff\xd9")
    assert (await result(client, response.json()["job_id"]))["state"] == "RETAKE"


async def test_wrong_person_and_correction(client):
    job_id = await demo(client)
    await result(client, job_id)
    assert (await client.post(f"/v1/jobs/{job_id}/next-candidate")).status_code == 200
    data = await result(client, job_id)
    assert data["state"] == "COMPLETE_ORG_ONLY"
    assert (
        await client.patch(
            f"/v1/jobs/{job_id}/extraction", json={"name": "Someone Else", "organization": "Unknown Labs"}
        )
    ).status_code == 200
    data = await result(client, job_id)
    assert data["state"] == "COMPLETE_ORG_ONLY" and not data["evidence"]
    assert "Avery" not in json.dumps(data["brief"])


async def test_cancel_and_forget_prevent_resurrection(client):
    client.app_ref.state.settings.mock_delay = 0.04
    job_id = await demo(client)
    assert (await client.post(f"/v1/jobs/{job_id}/cancel")).status_code == 200
    assert (await result(client, job_id))["state"] == "CANCELLED"
    assert (await client.delete(f"/v1/jobs/{job_id}")).status_code == 204
    await asyncio.sleep(0.1)
    assert (await client.get(f"/v1/jobs/{job_id}")).status_code == 404
    assert not client.app_ref.state.pipeline.cache


async def test_purge_and_ttl(client):
    job_id = await demo(client)
    await result(client, job_id)
    job = client.app_ref.state.pipeline.jobs[job_id]
    job.created = time.time() - 2000
    await client.app_ref.state.pipeline.sweep()
    assert (await client.get(f"/v1/jobs/{job_id}")).status_code == 404
    await demo(client)
    assert (await client.post("/v1/purge")).status_code == 204
    assert (await client.get("/v1/jobs")).json() == []


async def test_auth_csrf_and_origin(client):
    assert (await client.post("/v1/purge", headers={"X-CSRF-Token": "wrong"})).status_code == 403
    assert (await client.get("/v1/jobs", headers={"Origin": "https://attacker.invalid"})).status_code == 403
    assert (await client.get("/", headers={"Host": "attacker.invalid"})).status_code == 400
    client.cookies.clear()
    assert (await client.get("/v1/jobs")).status_code == 401


async def test_pairing_one_time_scoped_and_revocable(client):
    code = (await client.post("/v1/devices/pair-code")).json()["code"]
    pair = await client.post("/v1/devices/pair", json={"code": code, "device_id": "new-device"})
    assert pair.status_code == 200
    assert (
        await client.post("/v1/devices/pair", json={"code": code, "device_id": "other"})
    ).status_code == 401
    token = pair.json()["token"]
    h = {"Authorization": "Bearer " + token, "X-Device-ID": "new-device"}
    assert (await client.get("/v1/devices/new-device/config", headers=h)).status_code == 200
    assert (await client.get("/v1/devices/another/config", headers=h)).status_code == 403
    job_id = await demo(client)
    assert (await client.get(f"/v1/jobs/{job_id}", headers=h)).status_code == 404
    await client.delete("/v1/devices/new-device")
    client.cookies.clear()
    assert (await client.get("/v1/devices/new-device/config", headers=h)).status_code == 401


async def test_retake_limit_never_bypasses_invalid_jpeg(client):
    output = io.BytesIO()
    Image.new("RGB", (500, 500), "black").save(output, format="JPEG")
    states = []
    for n in range(3):
        response = await client.post(
            "/v1/captures",
            headers={"X-Capture-ID": f"lowlight-{n}", "Content-Type": "image/jpeg"},
            content=output.getvalue(),
        )
        states.append((await result(client, response.json()["job_id"]))["state"])
    assert states == ["RETAKE", "RETAKE", "COMPLETE"]
    with pytest.raises(ValueError):
        gate(b"bad")


async def test_kill_switch(client):
    assert (await client.post("/v1/kill-switch")).json()["paused"]
    assert (await client.post("/v1/demo")).status_code == 503
    assert (await client.get("/readyz")).status_code == 503


async def test_confirmation(client):
    client.app_ref.state.settings.require_confirmation = True
    job_id = await demo(client)
    for _ in range(100):
        if client.app_ref.state.pipeline.jobs[job_id].state == State.AWAITING_CONFIRMATION:
            break
        await asyncio.sleep(0.01)
    assert (await client.post(f"/v1/jobs/{job_id}/confirm")).status_code == 200
    assert (await result(client, job_id))["state"] == "COMPLETE"


async def test_timeout_degrades_without_claims(client):
    client.app_ref.state.settings.stage_timeout = 0.001
    client.app_ref.state.settings.mock_delay = 0.1
    data = await result(client, await demo(client))
    assert data["state"] == "COMPLETE_ORG_ONLY"
    assert not data["brief"]["summary"]


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "javascript:alert(1)",
        "https://127.0.0.1/a",
        "https://user:password@example.com/",
        "https://foo.linkedin.com/a",
        "https://host.local/",
    ],
)
def test_unsafe_urls(url):
    assert safe_url(url) is None


async def test_identity_corroboration_and_citation_validation(settings):
    mock = MockAdapter(settings)
    extraction = await mock.extract(b"", "success", None)
    research = Research.model_validate_json((ROOT / "host/fixtures/research.json").read_text())
    chosen, confidence, evidence = resolve(research, extraction, [])
    assert chosen and confidence == "high"
    research.evidence[1].url = "https://example.com/other"
    _, confidence, _ = resolve(research, extraction, [])
    assert confidence == "medium"
    research.candidates[0].organization = "Different Company"
    chosen, confidence, evidence = resolve(research, extraction, [])
    assert chosen is None and confidence == "organization_only"
    assert all(e.subject == "organization" for e in evidence)
    brief = await mock.synthesize({"confidence": "high"}, None)
    brief.summary[0].source_ids = ["e999"]
    assert validate_brief(brief, evidence, "high")


async def test_meta_payload_schema_privacy_and_grounding(settings):
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps({"card_type": "conference_badge", "confidence": 0.95}),
                            }
                        ],
                    }
                ],
            },
        )

    adapter = MetaMuseAdapter(settings, httpx.MockTransport(handler))
    budget = Budget(1, Ledger(10))
    result = await adapter.classify(b"fake", "", budget)
    assert result.card_type == "conference_badge"
    payload = calls[0]
    assert payload["store"] is False and payload["text"]["format"]["strict"] is True
    assert "tools" not in payload
    assert payload["input"][0]["content"][1]["type"] == "input_image"
    assert budget.input_tokens == 10
    await adapter.close()


async def test_rejected_card_never_extracts_or_researches(settings):
    class Spy(MockAdapter):
        async def extract(self, *args):
            raise AssertionError("should not extract rejected card")

        async def research(self, *args):
            raise AssertionError("should not research rejected card")

    app = create_app(settings, Spy(settings))
    pipeline = app.state.pipeline
    job = pipeline.add("d", "c", demo_jpeg(), "rejected")
    await job.task
    assert job.state == State.REJECTED_CARD_TYPE and job.extraction is None
    assert job.snapshot()["classification"] == {"card_type": "government_id", "confidence": 0.99}
    assert all(not isinstance(value, bytes) for value in vars(job).values())
    await pipeline.close()


@pytest.mark.parametrize(
    ("confidence", "expected"), [(0.2, State.COMPLETE), (0.19, State.REJECTED_CARD_TYPE)]
)
async def test_classification_confidence_cutoff(settings, confidence, expected):
    class Classifier(MockAdapter):
        async def classify(self, image, scenario, budget):
            return Classification(card_type="conference_badge", confidence=confidence)

    app = create_app(settings, Classifier(settings))
    pipeline = app.state.pipeline
    job = pipeline.add("d", "c", demo_jpeg())
    await job.task
    assert job.state == expected
    assert job.snapshot()["classification"]["confidence"] == confidence
    await pipeline.close()


async def test_failed_verification_repairs_once_then_degrades(settings):
    from badge_briefing.domain import Verification

    class Reject(MockAdapter):
        count = 0

        async def verify(self, *args):
            self.count += 1
            return Verification(verdict="repair", reasons=["unsupported claim"])

    provider = Reject(settings)
    app = create_app(settings, provider)
    job = app.state.pipeline.add("d", "c", demo_jpeg())
    await job.task
    assert provider.count == 2 and job.state == State.COMPLETE_ORG_ONLY
    assert not job.brief.summary
    await app.state.pipeline.close()


def test_standard_only(settings):
    with pytest.raises(ValueError):
        Settings(pin="long-enough-pin", model="muse-spark-1.3-contributor")


async def test_ui_csp_and_assets(client):
    response = await client.get("/")
    assert response.status_code == 200 and "WEART" in response.text
    assert "unsafe-inline" not in response.headers["Content-Security-Policy"]
    assert (await client.get("/app.js")).status_code == 200
    assert (await client.get("/v1/openapi")).status_code == 200
