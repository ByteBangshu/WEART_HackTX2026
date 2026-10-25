"""Capture a JPEG from ESP32 USB serial and submit it to the local live WEART app."""

import argparse
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx
import serial

ROOT = Path(__file__).resolve().parents[1]
MAX_JPEG_BYTES = 3_000_000
HEADER = re.compile(rb"WEART_USB_JPEG ([0-9]+)")
TERMINAL = {"COMPLETE", "COMPLETE_ORG_ONLY", "RETAKE", "FAILED", "CANCELLED", "EXPIRED"}


def local_pin():
    pin = os.getenv("WEART_PIN")
    if pin:
        return pin
    try:
        config = json.loads((ROOT / "runtime/local-config.json").read_text(encoding="utf-8"))
        pin = config.get("pin")
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("Set WEART_PIN or create runtime/local-config.json with tools/run.py.") from exc
    if not isinstance(pin, str) or len(pin) < 10:
        raise SystemExit("The local WEART passphrase is missing or invalid.")
    return pin


def check_local_host(host):
    parsed = urlparse(host)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise SystemExit("The USB bridge only sends the passphrase and image to the local HTTP app.")


def read_jpeg(port, wait_seconds):
    deadline = time.monotonic() + wait_seconds
    length = None
    while time.monotonic() < deadline:
        match = HEADER.search(port.readline())
        if match:
            length = int(match.group(1))
            break
    if length is None:
        raise TimeoutError("No ESP32 capture received before timeout; short-press its capture button.")
    if not 0 < length <= MAX_JPEG_BYTES:
        raise ValueError(f"ESP32 announced an invalid JPEG length: {length}.")

    image = bytearray()
    deadline = time.monotonic() + max(30, length / 5000 + 10)
    while len(image) < length and time.monotonic() < deadline:
        chunk = port.read(min(8192, length - len(image)))
        if chunk:
            image.extend(chunk)
    if len(image) != length:
        raise TimeoutError(f"Incomplete USB frame: received {len(image)} of {length} bytes.")
    trailer = b""
    while time.monotonic() < deadline and not trailer.strip():
        trailer = port.readline()
    if b"WEART_USB_END" not in trailer:
        raise ValueError("ESP32 USB frame trailer was missing.")
    if not image.startswith(b"\xff\xd8") or not image.endswith(b"\xff\xd9"):
        raise ValueError("ESP32 transfer is not a complete JPEG.")
    return bytes(image)


def print_summary(result):
    print(f"Job state: {result['state']}")
    if result.get("message"):
        print(result["message"])
    extraction = result.get("extraction") or {}
    if extraction:
        print(
            "Card: "
            + " · ".join(
                value
                for value in (
                    extraction.get("name", {}).get("text"),
                    extraction.get("job_title", {}).get("text"),
                    extraction.get("organization", {}).get("text"),
                )
                if value
            )
        )
    brief = result.get("brief")
    if not brief:
        return
    print(f"\n{brief['headline']['text']}")
    for claim in brief.get("summary", []):
        print(f"- {claim['text']}")
    for interest in brief.get("interests", []):
        print(f"- Interest: {interest['text']}")
    print(f"Identity confidence: {brief['confidence']}")
    for caveat in brief.get("caveats", []):
        print(f"Caveat: {caveat}")
    evidence = {item["id"]: item for item in result.get("evidence", [])}
    used_ids = {
        source_id
        for claim in [brief["headline"], *brief.get("summary", []), *brief.get("interests", [])]
        for source_id in claim.get("source_ids", [])
    }
    for source_id in sorted(used_ids):
        if source_id in evidence:
            print(f"Source {source_id}: {evidence[source_id]['title']} — {evidence[source_id]['url']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/ttyUSB0", help="ESP32 USB serial port")
    parser.add_argument("--host", default="http://127.0.0.1:8765", help="Local WEART app origin")
    parser.add_argument("--wait", type=int, default=300, help="Seconds to wait for the capture button")
    parser.add_argument("--job-timeout", type=int, default=120, help="Seconds to wait for app processing")
    parser.add_argument(
        "--save-image", type=Path, help="Save the captured JPEG here after the app accepts it"
    )
    args = parser.parse_args()
    if args.wait < 1 or args.job_timeout < 1:
        parser.error("--wait and --job-timeout must be positive")
    if args.save_image and args.save_image.exists():
        raise SystemExit(f"Refusing to overwrite existing image: {args.save_image}")
    check_local_host(args.host)

    with httpx.Client(base_url=args.host, timeout=20, trust_env=False) as client:
        ready = client.get("/readyz")
        ready.raise_for_status()
        if ready.json().get("provider") != "meta":
            raise SystemExit("Live Meta mode is required; refusing to create a fictional mock summary.")
        login = client.post("/v1/session", json={"pin": local_pin()})
        login.raise_for_status()
        csrf = login.json()["csrf"]
        try:
            session = client.get("/v1/session")
            session.raise_for_status()
            if not session.json().get("search_enabled"):
                raise SystemExit(
                    "Source-backed summaries require explicitly enabling unbounded provider search cost "
                    "with WEART_ALLOW_UNBOUNDED_SEARCH=true."
                )

            port = serial.Serial(port=None, baudrate=115200, timeout=0.5)
            port.port = args.port
            port.dtr = False
            port.rts = False
            with port:
                print(
                    f"Listening on {args.port}; short-press the ESP32 capture button.",
                    flush=True,
                )
                image = read_jpeg(port, args.wait)

            response = client.post(
                "/v1/captures",
                headers={
                    "X-CSRF-Token": csrf,
                    "X-Capture-ID": uuid.uuid4().hex,
                    "Content-Type": "image/jpeg",
                },
                content=image,
            )
            response.raise_for_status()
            job_id = response.json()["job_id"]
            print(f"ESP32 image sent to the local app; job {job_id}.")
            if args.save_image:
                with args.save_image.open("xb") as image_file:
                    image_file.write(image)
                print(f"Captured JPEG saved to {args.save_image}.")
            deadline = time.monotonic() + args.job_timeout
            while time.monotonic() < deadline:
                status = client.get(f"/v1/jobs/{job_id}")
                status.raise_for_status()
                result = status.json()
                if result["state"] in TERMINAL:
                    break
                time.sleep(0.5)
            else:
                print(f"Job still processing: {args.host} (job {job_id})")
                return
            print_summary(result)
        finally:
            client.delete("/v1/session", headers={"X-CSRF-Token": csrf}).raise_for_status()


if __name__ == "__main__":
    try:
        main()
    except (httpx.HTTPError, serial.SerialException, TimeoutError, ValueError) as exc:
        print(f"ESP32 capture failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
