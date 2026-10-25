import asyncio
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw

from .config import ROOT, Settings
from .domain import TERMINAL, Correction, State
from .pipeline import Pipeline
from .providers import MetaMuseAdapter, MockAdapter
from .quality import MAX_BYTES


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def demo_jpeg():
    image = Image.new("RGB", (1200, 800), "#183f35")
    draw = ImageDraw.Draw(image)
    draw.rectangle((60, 60, 1140, 740), fill="#eee8d8")
    for y, label in [
        (110, "FICTIONAL DEMO CONFERENCE"),
        (270, "AVERY CHEN"),
        (410, "EXAMPLE ROBOTICS"),
        (550, "Robotics Engineer"),
    ]:
        draw.text((110, y), label, fill="#122923", font_size=48)
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90)
    return output.getvalue()


def create_app(settings=None, provider=None):
    settings = settings or Settings.load()
    structlog.configure(
        processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.JSONRenderer()]
    )
    pipeline = Pipeline(
        settings,
        provider or (MockAdapter(settings) if settings.provider == "mock" else MetaMuseAdapter(settings)),
    )
    sessions: dict[str, dict[str, Any]] = {}
    devices = {settings.device_id: digest(settings.device_token)} if settings.device_token else {}
    registry = Path(settings.device_registry) if settings.device_registry else None
    if registry and registry.exists():
        loaded = json.loads(registry.read_text())
        if (
            not isinstance(loaded, dict)
            or len(loaded) > 8
            or any(
                not isinstance(k, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", k)
                or not isinstance(v, str)
                or not re.fullmatch(r"[0-9a-f]{64}", v)
                for k, v in loaded.items()
            )
        ):
            raise ValueError("Invalid local device registry")
        devices = loaded

    def persist_devices():
        if registry:
            registry.parent.mkdir(parents=True, exist_ok=True)
            temporary = registry.with_suffix(".tmp")
            temporary.write_text(json.dumps(devices), encoding="utf-8")
            temporary.chmod(0o600)
            temporary.replace(registry)

    if registry and not registry.exists():
        persist_devices()
    pair_codes: dict[str, dict[str, Any]] = {}
    rates: dict[str, float] = {}
    login_attempts: dict[str, tuple[float, int]] = {}
    ingestion = 0
    pending_uploads: dict[tuple[str, str], asyncio.Future] = {}
    usb_process = None

    @asynccontextmanager
    async def lifespan(app):
        async def cleanup():
            while True:
                await asyncio.sleep(5)
                await pipeline.sweep()
                for mapping in (sessions, pair_codes):
                    for key, value in list(mapping.items()):
                        if value["expires"] < time.time():
                            mapping.pop(key, None)
                for key, attempt in list(login_attempts.items()):
                    if attempt[0] < time.time() - 60:
                        login_attempts.pop(key, None)

        task = asyncio.create_task(cleanup())
        yield
        if usb_process is not None and usb_process.poll() is None:
            usb_process.terminate()
            await asyncio.to_thread(usb_process.wait)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await pipeline.close()

    app = FastAPI(
        title="WEART Badge Briefing",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.pipeline = pipeline
    app.state.settings = settings

    def auth(request, ui_only=False):
        token = request.headers.get("authorization", "")
        device = request.headers.get("x-device-id", "")
        if not ui_only and token.startswith("Bearer ") and device in devices:
            if hmac.compare_digest(devices[device], digest(token[7:])):
                return device
        session = sessions.get(digest(request.cookies.get("weart_session", "")))
        if not session or session["expires"] < time.time():
            raise HTTPException(401, "Sign in or pair the device first")
        if request.method not in {"GET", "HEAD"}:
            if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), session["csrf"]):
                raise HTTPException(403, "CSRF token required")
        return "ui"

    def owned(request, job_id):
        who = auth(request)
        job = pipeline.jobs.get(job_id)
        if not job or job.deleted or time.time() - job.created > settings.ttl_seconds:
            raise HTTPException(404, "Briefing expired or was forgotten")
        if who != "ui" and who != job.device:
            raise HTTPException(404, "Job not found")
        return job

    def capacity():
        if settings.kill_switch:
            raise HTTPException(503, "Captures paused by operator")
        active = sum(j.task is not None and not j.task.done() for j in pipeline.jobs.values())
        if len(pipeline.jobs) >= settings.max_jobs or active + ingestion >= settings.max_active:
            raise HTTPException(429, "Host busy; wait or forget an older briefing")

    @app.middleware("http")
    async def security(request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                limit = MAX_BYTES if request.url.path == "/v1/captures" else 8192
                if int(content_length) < 0 or int(content_length) > limit:
                    return JSONResponse({"detail": "Request too large"}, status_code=413)
            except ValueError:
                return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
        origin = request.headers.get("origin")
        if origin and origin != settings.origin:
            return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
        # Host validation prevents DNS-rebinding to loopback services.
        from urllib.parse import urlsplit

        if request.headers.get("host") != urlsplit(settings.origin).netloc:
            return JSONResponse({"detail": "Host not allowed"}, status_code=400)
        response = await call_next(request)
        response.headers.update(
            {
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                "Cache-Control": "no-store",
            }
        )
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse({"detail": "Request did not match the required schema"}, status_code=422)

    @app.get("/healthz")
    async def health():
        return {"ok": True}

    @app.get("/readyz")
    async def ready():
        return JSONResponse(
            {"ready": not settings.kill_switch, "provider": settings.provider},
            status_code=503 if settings.kill_switch else 200,
        )

    @app.post("/v1/session")
    async def login(request: Request):
        key = request.client.host if request.client else "local"
        start, count = login_attempts.get(key, (time.time(), 0))
        if time.time() - start > 60:
            start, count = time.time(), 0
        if count >= 5 or len(login_attempts) >= 1000:
            raise HTTPException(429, "Too many sign-in attempts; wait a minute")
        login_attempts[key] = (start, count + 1)
        raw = await small_body(request)
        try:
            supplied = json.loads(raw).get("pin", "")
        except (ValueError, AttributeError):
            raise HTTPException(400, "Invalid sign-in request") from None
        if not isinstance(supplied, str) or not hmac.compare_digest(digest(supplied), digest(settings.pin)):
            raise HTTPException(401, "Incorrect local passphrase")
        if len(sessions) >= 32:
            raise HTTPException(429, "Session limit reached")
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        sessions[digest(token)] = {"csrf": csrf, "expires": time.time() + 8 * 3600}
        response = JSONResponse({"csrf": csrf})
        response.set_cookie(
            "weart_session",
            token,
            httponly=True,
            samesite="strict",
            secure=settings.origin.startswith("https://"),
            max_age=8 * 3600,
        )
        return response

    @app.get("/v1/session")
    async def session(request: Request):
        auth(request, True)
        return {
            "csrf": sessions[digest(request.cookies["weart_session"])]["csrf"],
            "provider": settings.provider,
            "require_confirmation": settings.require_confirmation,
            "ttl_minutes": settings.ttl_seconds // 60,
            "search_enabled": settings.allow_unbounded_search,
        }

    @app.delete("/v1/session")
    async def logout(request: Request):
        auth(request, True)
        sessions.pop(digest(request.cookies.get("weart_session", "")), None)
        response = Response(status_code=204)
        response.delete_cookie("weart_session")
        return response

    @app.get("/v1/openapi")
    async def openapi(request: Request):
        auth(request, True)
        return app.openapi()

    @app.post("/v1/captures", status_code=202)
    async def capture(request: Request):
        nonlocal ingestion
        who = auth(request)
        capture_id = request.headers.get("x-capture-id", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", capture_id):
            raise HTTPException(400, "X-Capture-ID must contain 8–80 letters, digits, underscores or hyphens")
        existing = pipeline.dedupe.get((who, capture_id))
        if existing and existing in pipeline.jobs:
            return {"job_id": existing, "duplicate": True}
        capture_key = (who, capture_id)
        if capture_key in pending_uploads:
            job_id = await asyncio.shield(pending_uploads[capture_key])
            if job_id is None:
                raise HTTPException(409, "Original upload failed; retry this capture")
            return {"job_id": job_id, "duplicate": True}
        capacity()
        if time.monotonic() - rates.get(who, -1e9) < settings.rate_seconds:
            raise HTTPException(429, "Wait five seconds between captures")
        if request.headers.get("content-type", "").split(";")[0] != "image/jpeg":
            raise HTTPException(415, "Send a raw image/jpeg body")
        future = asyncio.get_running_loop().create_future()
        pending_uploads[capture_key] = future
        ingestion += 1
        try:
            async with asyncio.timeout(15):
                data = bytearray()
                async for chunk in request.stream():
                    if len(data) + len(chunk) > MAX_BYTES:
                        raise HTTPException(413, "JPEG exceeds 10 MB")
                    data.extend(chunk)
            rates[who] = time.monotonic()
            job = pipeline.add(who, capture_id, bytes(data))
            future.set_result(job.id)
            data.clear()
            return {"job_id": job.id, "duplicate": False}
        except TimeoutError:
            raise HTTPException(408, "Upload timed out") from None
        finally:
            ingestion -= 1
            pending_uploads.pop(capture_key, None)
            if not future.done():
                future.set_result(None)

    @app.post("/v1/usb-capture", status_code=202)
    async def usb_capture(request: Request):
        nonlocal usb_process
        auth(request, True)
        capacity()
        if settings.provider != "meta":
            raise HTTPException(409, "Start the app in live mode to capture from ESP32.")
        if not settings.allow_unbounded_search:
            raise HTTPException(409, "Enable web research on the host before starting an ESP32 briefing.")
        port = os.getenv("WEART_USB_PORT", "").strip()
        if not port:
            raise HTTPException(409, "Set WEART_USB_PORT to the ESP32 serial port and restart the app.")
        if usb_process is not None and usb_process.poll() is None:
            raise HTTPException(409, "An ESP32 capture is already running.")
        env = os.environ.copy()
        env["WEART_PIN"] = settings.pin
        try:
            usb_process = subprocess.Popen(
                [sys.executable, str(ROOT / "tools/esp32_usb_capture.py"),
                 "--port", port, "--host", settings.origin, "--wait", "120", "--submit-only"],
                cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
            )
        except OSError:
            raise HTTPException(503, "Could not start the USB capture bridge.") from None
        return {"running": True}

    @app.get("/v1/usb-capture")
    async def usb_capture_status(request: Request):
        auth(request, True)
        code = usb_process.poll() if usb_process is not None else None
        return {"running": usb_process is not None and code is None, "exit_code": code}

    @app.post("/v1/demo", status_code=202)
    async def demo(request: Request):
        auth(request, True)
        if settings.provider != "mock":
            raise HTTPException(409, "Demo is available only with the offline mock provider")
        capacity()
        scenario = request.query_params.get("scenario", "success")
        if scenario not in {"success", "organization", "missing"}:
            raise HTTPException(400, "Unknown demo scenario")
        job = pipeline.add("ui", secrets.token_hex(16), demo_jpeg(), scenario)
        return {"job_id": job.id}

    @app.get("/v1/jobs")
    async def jobs(request: Request):
        auth(request, True)
        await pipeline.sweep()
        return [{"id": j.id, "state": j.state, "created_at": j.created} for j in pipeline.jobs.values()]

    @app.get("/v1/jobs/{job_id}")
    async def status(job_id: str, request: Request):
        job = owned(request, job_id)
        if request.headers.get("authorization", "").startswith("Bearer "):
            return {
                "id": job.id,
                "state": job.state,
                "message": job.message,
                "device_lines": job.brief.device_lines if job.brief else [],
                "terminal": job.state in TERMINAL,
            }
        return job.snapshot(settings.provider == "mock")

    @app.get("/v1/jobs/{job_id}/brief")
    async def brief(job_id: str, request: Request):
        job = owned(request, job_id)
        if not job.brief:
            raise HTTPException(409, "Briefing not ready")
        return job.snapshot(settings.provider == "mock")

    @app.get("/v1/jobs/{job_id}/events")
    async def events(job_id: str, request: Request):
        job = owned(request, job_id)

        async def stream():
            last = -1
            while not job.deleted:
                # Recheck authentication and TTL on long-lived SSE connections.
                try:
                    owned(request, job_id)
                except HTTPException:
                    break
                job.changed.clear()
                seq = len(job.events)
                if seq != last:
                    yield f"id: {seq}\nevent: progress\ndata: {json.dumps(job.snapshot(settings.provider == 'mock'))}\n\n"
                    last = seq
                if job.state in TERMINAL or await request.is_disconnected():
                    return
                try:
                    await asyncio.wait_for(job.changed.wait(), timeout=10)
                except TimeoutError:
                    yield ": heartbeat\n\n"
            yield "event: forgotten\ndata: {}\n\n"

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    @app.patch("/v1/jobs/{job_id}/extraction")
    async def correct(job_id: str, body: Correction, request: Request):
        auth(request, True)
        job = owned(request, job_id)
        if not job.extraction or job.state in {State.CANCELLED, State.RETAKE}:
            raise HTTPException(409, "No accepted extraction to correct")
        if job.task and not job.task.done():
            job.task.cancel()
            await asyncio.gather(job.task, return_exceptions=True)
        pipeline.cache.pop(pipeline.key(job.extraction), None)
        for key in ("name", "organization"):
            value = getattr(body, key).strip()
            if key == "organization" and not value:
                raise HTTPException(422, "Organization cannot be blank")
            getattr(job.extraction, key).text = value
            getattr(job.extraction, key).normalized = value
            getattr(job.extraction, key).confidence = 1.0 if value else 0.0
        job.excluded.clear()
        await pipeline.restart(job)
        return {"job_id": job.id}

    @app.post("/v1/jobs/{job_id}/confirm")
    async def confirm(job_id: str, request: Request):
        auth(request, True)
        job = owned(request, job_id)
        if job.state != State.AWAITING_CONFIRMATION:
            raise HTTPException(409, "Job is not awaiting confirmation")
        if not job.extraction or not job.extraction.organization.normalized:
            raise HTTPException(409, "Enter an organization to continue")
        for key in ("name", "organization"):
            field = getattr(job.extraction, key)
            if field.normalized:
                field.confidence = 1.0
        job.confirmed.set()
        return {"ok": True}

    @app.post("/v1/jobs/{job_id}/next-candidate")
    async def next_candidate(job_id: str, request: Request):
        auth(request, True)
        job = owned(request, job_id)
        if job.state not in {State.COMPLETE, State.COMPLETE_ORG_ONLY}:
            raise HTTPException(409, "Wait for the current result")
        if job.candidate:
            job.excluded.append(job.candidate)
        if len(job.excluded) > 6:
            raise HTTPException(409, "Please rescan or correct the extracted fields")
        await pipeline.restart(job)
        return {"job_id": job.id}

    @app.post("/v1/jobs/{job_id}/cancel")
    async def cancel(job_id: str, request: Request):
        job = owned(request, job_id)
        if job.task and not job.task.done():
            job.task.cancel()
            await asyncio.gather(job.task, return_exceptions=True)
            job.emit(State.CANCELLED, "Capture cancelled")
        return {"state": job.state}

    @app.delete("/v1/jobs/{job_id}", status_code=204)
    async def forget(job_id: str, request: Request):
        auth(request, True)
        await pipeline.forget(owned(request, job_id))

    @app.post("/v1/purge", status_code=204)
    async def purge(request: Request):
        auth(request, True)
        for job in list(pipeline.jobs.values()):
            await pipeline.forget(job)
        pipeline.cache.clear()

    @app.post("/v1/kill-switch")
    async def kill(request: Request):
        auth(request, True)
        settings.kill_switch = not settings.kill_switch
        if settings.kill_switch:
            for job in list(pipeline.jobs.values()):
                if job.task and not job.task.done():
                    job.task.cancel()
            await asyncio.gather(*(j.task for j in pipeline.jobs.values() if j.task), return_exceptions=True)
        return {"paused": settings.kill_switch}

    @app.post("/v1/devices/pair-code")
    async def pair_code(request: Request):
        auth(request, True)
        if len(pair_codes) >= 10:
            raise HTTPException(429, "Too many pending pairing codes")
        code = secrets.token_hex(8)
        pair_codes[digest(code)] = {"expires": time.time() + 300}
        return {"code": code, "expires_in": 300}

    @app.post("/v1/devices/pair")
    async def pair(request: Request):
        raw = await small_body(request)
        try:
            body = json.loads(raw)
            device, code = body["device_id"], body["code"]
        except (ValueError, KeyError, TypeError):
            raise HTTPException(400, "Invalid pairing request") from None
        if (
            not isinstance(device, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", device)
            or not isinstance(code, str)
        ):
            raise HTTPException(400, "Invalid device ID or code")
        entry = pair_codes.get(digest(code))
        if not entry or entry["expires"] < time.time():
            raise HTTPException(401, "Invalid or expired pairing code")
        if device in devices or len(devices) >= 8:
            raise HTTPException(409, "Device already paired or device limit reached")
        pair_codes.pop(digest(code))
        token = secrets.token_urlsafe(32)
        devices[device] = digest(token)
        persist_devices()
        return {"device_id": device, "token": token}

    @app.get("/v1/devices/{device}/config")
    async def device_config(device: str, request: Request):
        who = auth(request)
        if who != "ui" and who != device:
            raise HTTPException(403)
        return {"jpeg_quality": 12, "burst": 3, "warmup": 4, "poll_ms": 1000, "paused": settings.kill_switch}

    @app.delete("/v1/devices/{device}", status_code=204)
    async def revoke(device: str, request: Request):
        auth(request, True)
        devices.pop(device, None)
        persist_devices()
        rates.pop(device, None)

    @app.get("/metrics")
    async def metrics(request: Request):
        auth(request, True)
        return Response(
            f"weart_jobs {len(pipeline.jobs)}\nweart_completed_total {pipeline.completed}\nweart_failed_total {pipeline.failed}\nweart_budget_reserved_usd {pipeline.ledger.reserved:.6f}\n",
            media_type="text/plain",
        )

    app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
    return app


async def small_body(request):
    data = bytearray()
    async with asyncio.timeout(5):
        async for chunk in request.stream():
            if len(data) + len(chunk) > 4096:
                raise HTTPException(413, "Request too large")
            data.extend(chunk)
    return bytes(data)
