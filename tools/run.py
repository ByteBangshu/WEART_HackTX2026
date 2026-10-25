"""Run from any working directory. Secrets remain in local environment/runtime files."""

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "host/src"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Use Meta; requires MODEL_API_KEY")
    parser.add_argument("--init-only", action="store_true")
    args = parser.parse_args()
    runtime = ROOT / "runtime"
    runtime.mkdir(exist_ok=True)
    credentials = runtime / "local-config.json"
    if not credentials.exists():
        credentials.write_text(
            json.dumps(
                {"pin": secrets.token_urlsafe(18), "device_token": secrets.token_urlsafe(32)}, indent=2
            ),
            encoding="utf-8",
        )
        try:
            credentials.chmod(0o600)
        except OSError:
            pass
    local = json.loads(credentials.read_text())
    os.environ.setdefault("WEART_PIN", local["pin"])
    os.environ.setdefault("WEART_DEVICE_TOKEN", local["device_token"])
    os.environ.setdefault("WEART_DEVICE_REGISTRY", str(runtime / "devices.json"))
    os.environ.setdefault("WEART_PROVIDER", "meta" if args.live else "mock")
    print(f"Local passphrase and simulator token: {credentials}")
    print("Do not share this file. No model key is stored in it.")
    if args.init_only:
        return
    from badge_briefing.__main__ import main as serve

    print("Briefing desk: " + os.getenv("WEART_ORIGIN", "http://127.0.0.1:8765"))
    serve()


if __name__ == "__main__":
    main()
