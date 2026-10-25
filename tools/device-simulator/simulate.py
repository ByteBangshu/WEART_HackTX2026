"""Exercise the real capture endpoint without physical camera hardware."""

import argparse
import asyncio
import json
import os
import ssl
import sys
import time
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "host/src"))
from badge_briefing.app import demo_jpeg  # noqa: E402


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="http://127.0.0.1:8765")
    p.add_argument("--image", type=Path)
    p.add_argument("--ca", type=Path)
    p.add_argument("--device-id", default="badge-camera")
    p.add_argument(
        "--fault", choices=["none", "corrupt", "oversize", "slow", "drop", "replay"], default="none"
    )
    p.add_argument("--count", type=int, default=1)
    args = p.parse_args()
    token = os.getenv("WEART_DEVICE_TOKEN")
    if not token:
        token = json.loads((ROOT / "runtime/local-config.json").read_text())["device_token"]
    context = ssl.create_default_context(cafile=str(args.ca)) if args.ca else True
    data = args.image.read_bytes() if args.image else demo_jpeg()
    if args.fault == "corrupt":
        data = b"\xff\xd8broken\xff\xd9"
    if args.fault == "oversize":
        data = b"x" * 3_000_001
    async with httpx.AsyncClient(
        base_url=args.host,
        verify=context,
        timeout=20,
        headers={"Authorization": "Bearer " + token, "X-Device-ID": args.device_id},
    ) as client:
        for run in range(args.count):
            capture_id = uuid.uuid4().hex
            headers = {"Content-Type": "image/jpeg", "X-Capture-ID": capture_id}

            async def chunks():
                for pos in range(0, len(data), 4096):
                    yield data[pos : pos + 4096]
                    if args.fault == "drop":
                        raise httpx.ReadError("simulated transport interruption")
                    await asyncio.sleep(0.5)

            started = time.monotonic()
            try:
                response = await client.post(
                    "/v1/captures",
                    headers=headers,
                    content=chunks() if args.fault in {"slow", "drop"} else data,
                )
            except httpx.HTTPError:
                print(json.dumps({"run": run + 1, "outcome": "transport_fault"}))
                continue
            if response.status_code != 202:
                print(json.dumps({"run": run + 1, "http_status": response.status_code}))
                if args.fault == "none":
                    raise SystemExit(1)
                continue
            job_id = response.json()["job_id"]
            if args.fault == "replay":
                replay = await client.post("/v1/captures", headers=headers, content=data)
                assert replay.json()["job_id"] == job_id, "idempotency violated"
            while time.monotonic() - started < 75:
                status = await client.get("/v1/jobs/" + job_id)
                status.raise_for_status()
                result = status.json()
                if result["terminal"]:
                    print(
                        json.dumps(
                            {
                                "run": run + 1,
                                "job_id": job_id,
                                "state": result["state"],
                                "seconds": round(time.monotonic() - started, 2),
                            }
                        )
                    )
                    break
                await asyncio.sleep(0.5)
            else:
                raise SystemExit("Host job timed out")
            if run + 1 < args.count:
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
