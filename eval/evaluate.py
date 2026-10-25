"""Offline image-gate smoke test; --live explicitly measures extraction via Meta."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host/src"))
from badge_briefing.config import Settings  # noqa: E402
from badge_briefing.providers import Budget, Ledger, MetaMuseAdapter  # noqa: E402
from badge_briefing.quality import gate  # noqa: E402


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--limit", type=int, default=72)
    args = parser.parse_args()
    folder = ROOT / "eval/generated"
    labels = json.loads((folder / "gold.json").read_text(encoding="utf-8"))[: args.limit]
    settings = Settings.load() if args.live else None
    provider = MetaMuseAdapter(settings) if settings else None
    ledger = Ledger(settings.daily_cost_cap) if settings else None
    counts = {
        "good_total": 0,
        "good_correct": 0,
        "hard_total": 0,
        "hard_correct": 0,
        "negative_total": 0,
        "negative_rejected": 0,
        "quality_retake": 0,
    }
    try:
        for item in labels:
            image = (folder / item["image"]).read_bytes()
            quality = gate(image)
            counts["quality_retake"] += bool(quality.reasons)
            if not provider:
                continue
            budget = Budget(settings.job_cost_cap, ledger)
            card = await provider.classify(quality.jpeg, "", budget)
            accepted = (
                card.card_type in {"conference_badge", "corporate_id", "business_card"}
                and card.confidence >= 0.8
            )
            if item["difficulty"] == "negative":
                counts["negative_total"] += 1
                counts["negative_rejected"] += not accepted
                continue
            key = item["difficulty"]
            counts[key + "_total"] += 1
            if accepted:
                extraction = await provider.extract(quality.jpeg, "", budget)
                counts[key + "_correct"] += (
                    extraction.name.normalized.casefold() == item["name"].casefold()
                    and extraction.organization.normalized.casefold() == item["organization"].casefold()
                )
    finally:
        if provider:
            await provider.close()
    report = {
        "mode": "live_extraction" if args.live else "offline_gate_only",
        "fixtures": len(labels),
        **counts,
        "note": "Offline smoke does NOT measure OCR or model safety accuracy.",
    }
    (ROOT / "runtime").mkdir(exist_ok=True)
    (ROOT / "runtime/eval-report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    if args.live:
        for difficulty, target in [("good", 0.95), ("hard", 0.85), ("negative", 1.0)]:
            total = counts[difficulty + "_total"]
            correct = counts[difficulty + ("_rejected" if difficulty == "negative" else "_correct")]
            if not total or correct / total < target:
                raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
