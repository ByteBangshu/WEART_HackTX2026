import asyncio
import hashlib
import time
import uuid
from dataclasses import dataclass, field

import structlog

from .config import Settings
from .domain import TERMINAL, Brief, Claim, Extraction, State
from .ports import Provider
from .providers import Budget, Ledger
from .quality import gate
from .safety import resolve, validate_brief

log = structlog.get_logger()


@dataclass
class Job:
    device: str
    capture: str
    budget: Budget
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created: float = field(default_factory=time.time)
    started: float = field(default_factory=time.time)
    state: State = State.RECEIVED
    message: str = "Capture received"
    extraction: Extraction | None = None
    brief: Brief | None = None
    evidence: list = field(default_factory=list)
    candidate: str | None = None
    excluded: list[str] = field(default_factory=list)
    events: list = field(default_factory=list)
    task: asyncio.Task | None = None
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    confirmed: asyncio.Event = field(default_factory=asyncio.Event)
    deleted: bool = False
    quality: dict = field(default_factory=dict)
    revision: int = 0
    finished: float | None = None
    transition_at: float = field(default_factory=time.monotonic)
    stage_seconds: dict[str, float] = field(default_factory=dict)

    def snapshot(self, mock=False):
        return {
            "id": self.id,
            "state": self.state,
            "message": self.message,
            "created_at": self.created,
            "extraction": self.extraction.model_dump() if self.extraction else None,
            "brief": self.brief.model_dump() if self.brief else None,
            "evidence": [e.model_dump() for e in self.evidence],
            "quality": self.quality,
            "mock": mock,
            "revision": self.revision,
            "terminal": self.state in TERMINAL,
            "elapsed_seconds": round((self.finished or time.time()) - self.started, 1),
            "stage_seconds": self.stage_seconds,
            "usage": {
                "input_tokens": self.budget.input_tokens,
                "output_tokens": self.budget.output_tokens,
                "search_calls_observed": self.budget.searches,
                "estimated_usd": round(self.budget.estimated_cost, 5),
            },
            "transparency": "Compiled from public sources by AI; may be inaccurate.",
        }

    def emit(self, state, message):
        if self.deleted:
            return
        now = time.monotonic()
        self.stage_seconds[str(self.state)] = round(
            self.stage_seconds.get(str(self.state), 0) + now - self.transition_at, 3
        )
        self.transition_at = now
        self.state, self.message = state, message
        if state in TERMINAL:
            self.finished = time.time()
        event = {"seq": len(self.events) + 1, "state": str(state), "message": message}
        self.events.append(event)
        self.changed.set()
        log.info("job_transition", job_id=self.id, state=str(state))


class Pipeline:
    def __init__(self, settings: Settings, provider: Provider):
        self.settings, self.provider = settings, provider
        self.jobs: dict[str, Job] = {}
        self.dedupe: dict[tuple[str, str], str] = {}
        self.retakes: dict[str, int] = {}
        self.ledger = Ledger(settings.daily_cost_cap)
        self.cache: dict[str, tuple] = {}
        self.cache_salt = uuid.uuid4().hex
        self.completed = 0
        self.failed = 0

    def key(self, extraction):
        return hashlib.sha256(
            (
                self.cache_salt
                + extraction.name.normalized.casefold()
                + "\0"
                + extraction.organization.normalized.casefold()
            ).encode()
        ).hexdigest()

    def add(self, device, capture, image, scenario="success"):
        job = Job(device=device, capture=capture, budget=Budget(self.settings.job_cost_cap, self.ledger))
        self.jobs[job.id] = job
        self.dedupe[(device, capture)] = job.id
        job.emit(State.RECEIVED, "Capture received")
        job.task = asyncio.create_task(self.run(job, image, scenario))
        return job

    async def step(self, call):
        async with asyncio.timeout(self.settings.stage_timeout):
            return await call

    async def run(self, job, image=None, scenario="success"):
        try:
            async with asyncio.timeout(self.settings.job_timeout):
                if image is not None:
                    try:
                        try:
                            quality = await asyncio.to_thread(gate, image)
                        except ValueError:
                            job.emit(
                                State.RETAKE,
                                "Invalid JPEG or unsafe image dimensions. Capture another image.",
                            )
                            return
                        job.quality = quality.metrics
                        if quality.reasons and self.retakes.get(job.device, 0) < 2:
                            self.retakes[job.device] = self.retakes.get(job.device, 0) + 1
                            job.emit(State.RETAKE, " ".join(quality.reasons))
                            return
                        self.retakes[job.device] = 0
                        image = quality.jpeg
                        del quality
                        job.emit(State.GATED, "JPEG checked; metadata removed")
                        job.emit(State.EXTRACTING, "Checking card type before reading professional fields")
                        classification = await self.step(self.provider.classify(image, scenario, job.budget))
                        if (
                            classification.card_type
                            not in {"conference_badge", "corporate_id", "business_card"}
                            or classification.confidence < 0.8
                        ):
                            job.emit(
                                State.REJECTED_CARD_TYPE,
                                "Only clearly identified professional badges and business cards are accepted. No research performed.",
                            )
                            return
                        extraction = await self.step(self.provider.extract(image, scenario, job.budget))
                        if extraction.card_type not in {"conference_badge", "corporate_id", "business_card"}:
                            job.emit(
                                State.REJECTED_CARD_TYPE,
                                "This card type is not supported. No research performed.",
                            )
                            return
                        job.extraction = extraction
                    finally:
                        image = None  # no image stored in Job, cache, events, or disk
                    if (
                        not job.extraction.organization.normalized
                        or job.extraction.legibility == "unreadable"
                    ):
                        job.emit(State.RETAKE, "The organization is unreadable. Please rescan.")
                        return
                    if self.settings.require_confirmation:
                        job.emit(
                            State.AWAITING_CONFIRMATION,
                            "Confirm or correct the extracted name and organization",
                        )
                        await job.confirmed.wait()
                if not job.extraction:
                    raise ValueError("Extraction required")
                job.emit(State.RESOLVING, "Checking identity against public professional sources")
                cache_key = self.key(job.extraction)
                cached = self.cache.get(cache_key)
                if cached and cached[0] > time.time() and not job.excluded:
                    research = cached[1].model_copy(deep=True)
                else:
                    research = await self.step(
                        self.provider.research(job.extraction, job.excluded, job.budget)
                    )
                    self.cache[cache_key] = (
                        time.time() + self.settings.ttl_seconds,
                        research.model_copy(deep=True),
                    )
                candidate, confidence, evidence = resolve(research, job.extraction, job.excluded)
                job.candidate = candidate.id if candidate else None
                job.evidence = evidence
                job.emit(
                    State.RESEARCHING,
                    "Collecting sourced professional context"
                    if candidate
                    else "Individual not verified; checking organization context",
                )
                if not evidence:
                    self.fallback(job, "No usable professional sources were found.")
                    return
                context = {
                    "candidate": candidate.model_dump() if candidate else None,
                    "confidence": confidence,
                    "evidence": [x.model_dump() for x in evidence],
                }
                for attempt in range(2):
                    job.emit(State.SYNTHESIZING, "Writing concise, source-linked conversation starters")
                    brief = await self.step(
                        self.provider.synthesize(context, job.budget, repair=bool(attempt))
                    )
                    job.emit(State.VERIFYING, "Checking claims, citations, and identity consistency")
                    problems = validate_brief(brief, evidence, confidence)
                    verification = await self.step(self.provider.verify(brief, context, job.budget))
                    if not problems and verification.verdict == "pass":
                        # Construct device text only from already verified claims.
                        brief.device_lines = [
                            brief.headline.text[:70],
                            (brief.starters[0].text if brief.starters else "See briefing on phone")[:165],
                        ]
                        job.brief = brief
                        self.completed += 1
                        job.emit(
                            State.COMPLETE if candidate else State.COMPLETE_ORG_ONLY,
                            "Briefing ready"
                            if candidate
                            else "Organization briefing ready; individual could not be verified",
                        )
                        return
                    if verification.verdict == "degrade":
                        break
                self.fallback(job, "The generated claims did not pass verification.")
        except asyncio.CancelledError:
            job.emit(State.CANCELLED, "Capture cancelled")
            raise
        except TimeoutError:
            self.fallback(job, "Research time limit reached; no unverified person claims are shown.")
        except Exception:
            # No exception text: provider errors could contain image data or personal content.
            self.failed += 1
            log.warning("job_stage_failed", job_id=job.id, state=str(job.state))
            if job.extraction:
                self.fallback(job, "Professional research is unavailable. Try again later.")
            else:
                job.emit(State.FAILED, "Card processing is unavailable. Please retry.")
        finally:
            image = None
            log.info(
                "job_finished",
                job_id=job.id,
                state=str(job.state),
                input_tokens=job.budget.input_tokens,
                output_tokens=job.budget.output_tokens,
                observed_search_calls=job.budget.searches,
                estimated_usd=round(job.budget.estimated_cost, 6),
            )

    def fallback(self, job, reason):
        # Fail closed: research snippets alone are not treated as verified summaries.
        job.evidence = []
        job.brief = Brief(
            headline=Claim(text="Professional context unavailable", source_ids=[]),
            summary=[],
            interests=[],
            starters=[],
            organization_snapshot=None,
            confidence="organization_only",
            caveats=[reason],
            could_not_verify=["Individual identity and professional background"],
            device_lines=["Could not verify person", "See phone for details"],
        )
        job.emit(State.COMPLETE_ORG_ONLY, "Limited result: no verified professional claims available")

    async def restart(self, job):
        if job.task and not job.task.done():
            job.task.cancel()
            await asyncio.gather(job.task, return_exceptions=True)
        if job.extraction:
            self.cache.pop(self.key(job.extraction), None)
        job.revision += 1
        job.brief, job.evidence = None, []
        job.finished = None
        job.started = time.time()
        job.task = asyncio.create_task(self.run(job))

    async def forget(self, job):
        job.deleted = True
        if job.task and not job.task.done():
            job.task.cancel()
            await asyncio.gather(job.task, return_exceptions=True)
        if job.extraction:
            self.cache.pop(self.key(job.extraction), None)
        job.extraction, job.brief, job.evidence = None, None, []
        job.changed.set()
        self.jobs.pop(job.id, None)
        self.dedupe.pop((job.device, job.capture), None)

    async def sweep(self):
        for job in list(self.jobs.values()):
            if time.time() - job.created > self.settings.ttl_seconds:
                job.emit(State.EXPIRED, "Briefing expired")
                await self.forget(job)
        self.cache = {k: v for k, v in self.cache.items() if v[0] > time.time()}

    async def close(self):
        for job in list(self.jobs.values()):
            await self.forget(job)
        self.cache.clear()
        await self.provider.close()
