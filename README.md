# WEART — A better first conversation

ESP32-S3 camera → local host → Muse Spark → source-linked professional briefing on your phone. **No résumé matching.** The default is an offline **fictional demo**: the mock provider does not read badge text. Never present mock results as live research.

## Run the demo

From this repository in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe tools/run.py
```

Open **http://127.0.0.1:8765**. The launcher creates `runtime/local-config.json`; use its `pin` value to unlock the UI. Keep this ignored file private. It also holds the simulator token, never the Meta key. Stop with Ctrl+C.

Click **Try a fictional demo**. Workspace controls offer successful identity, organization-only, and no-sources scenarios. Correct fields, try another candidate, cancel, forget, purge, or pause captures. The UI follows new device jobs automatically. Browser storage retains only the appearance preference and static application shell.

In another terminal, exercise the actual upload API and idempotency:

```powershell
.\.venv\Scripts\python.exe tools/device-simulator/simulate.py --fault replay
```

Other faults: `corrupt`, `oversize`, `slow`, `drop`. `--count 50` repeats simulated captures. This is not a physical-device soak test.

## Live Meta mode

Enter your key locally without echoing it:

```powershell
$secureKey = Read-Host 'Meta Model API key' -AsSecureString
$env:MODEL_API_KEY = [System.Net.NetworkCredential]::new('', $secureKey).Password
$env:WEART_PROVIDER = 'meta'
# Accepts that built-in search has no verified hard query-cost ceiling:
$env:WEART_ALLOW_UNBOUNDED_SEARCH = 'true'
.\.venv\Scripts\python.exe tools/run.py --live
```

Only Standard model IDs are accepted. Without the search opt-in, extraction runs but research degrades honestly to unavailable context. The adapter uses `muse-spark-1.3`, `store:false`, strict schemas, deadlines, bounded retries, a circuit breaker and request-cost reservations. Search usage/cost are estimates, **not guaranteed hard billing caps**. Use provider account spending controls too. [Provider facts and limitations](docs/adr/001-provider.md).

No live API accuracy or latency claim has been established. Classification sends the full image to Meta; restricted extraction fields do not prevent the provider seeing incidental image contents.

## Phone and physical camera

Loopback HTTP is for development. Non-loopback serving requires TLS and an explicit private LAN IP. Use a trusted 2.4 GHz WPA2 network/hotspot without client isolation.

```powershell
# Replace this address everywhere with the host's actual private LAN IP.
.\.venv\Scripts\python.exe tools/make_certificate.py --host 192.168.1.25
$env:WEART_BIND = '192.168.1.25'
$env:WEART_ORIGIN = 'https://192.168.1.25:8765'
$env:WEART_TLS_CERT = "$PWD\runtime\tls\host.pem"
$env:WEART_TLS_KEY = "$PWD\runtime\tls\host.key"
.\.venv\Scripts\python.exe tools/run.py
```

Manually trust **only** `runtime/tls/ca.pem` on the phone. The camera receives that CA through its physically commissioned setup portal. Never copy `host.key` or a model key to it. Use the exact configured HTTPS origin; do not bypass certificate warnings or expose this service to the internet. Limit any firewall exception to your private LAN.

Read [hardware setup](docs/hardware.md) before flashing. “ESP32-S3-CAM” is insufficient to select pins: firmware defaults to unset GPIOs and refuses camera initialization until the board mapping is confirmed.

## Implemented

- Async FastAPI jobs; bounded streaming JPEG ingress, per-device rate limits, capture-ID deduplication, cancellation, correction, SSE, expiry and purge.
- Hackathon capture flow: every decodable JPEG is sent straight to field extraction. Blur, darkness, and glare are advisory warnings; unreadable organization fields can be corrected in the phone UI before research.
- Size/pixel/decode checks, metadata stripping, and advisory image-quality heuristics. Decodable images always reach field extraction.
- Grounded research, identity confidence, independent-source checks, citation validation, independent verification and one repair attempt.
- Meta and mock adapters, memory-only briefs/cache, source-linked organization fallback and honest unavailable-context output.
- Passphrase sessions, CSRF/origin/Host checks, hashed revocable device tokens, single-use pairing codes, TLS support, CSP, kill switch and redacted logs.
- Phone-first responsive UI, dark mode, copy actions, sources, static-only PWA cache. No CDN or frontend build dependencies.
- ESP-IDF source: configurable pins, PSRAM JPEG burst, protected setup AP, NVS, certificate-validated upload/retries, polling, button cancellation, RGB feedback, reconnect, watchdog, crash recovery and optional deep sleep.
- Simulator, evaluation generator/harness, tests, pinned dependencies, CI and operating documentation.

## Verify

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check host tools eval
.\.venv\Scripts\python.exe -m mypy host/src
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check web/app.js
node --check web/sw.js
.\.venv\Scripts\python.exe eval/generate.py
.\.venv\Scripts\python.exe eval/evaluate.py
.\.venv\Scripts\python.exe -m pip_audit -r requirements.lock
```

`eval/evaluate.py --live` makes billable extraction calls with your key. Offline evaluation checks image processing only, **not OCR accuracy**. The 60 fictional badges and 12 negatives are a smoke dataset, not proof of real-world safety/performance. Broader scripts, realistic negatives and a resolution benchmark remain necessary.

See [verification status](docs/verification.md), [runbook](docs/runbook.md), [architecture](docs/architecture.md) and [threat model](docs/threat-model.md). A configured ESP-IDF build and 50 physical captures must pass before claiming hardware readiness. Autofocus, automatic captive-portal detection, double-press preview, battery measurement, full light sleep, BSSID caching, signed OTA, display, audio, local OCR and encrypted history remain stretch work.

## Privacy

Public professional information only; no face recognition, sensitive profiling, login-walled scraping or stored profiles. Images live in application memory and are released after extraction/failure; this is not cryptographic RAM erasure or a provider deletion guarantee. Results/cache expire after 30 minutes. Logs omit personal payloads.

Review applicable local law (including GDPR/CCPA where relevant), event rules, and obtain consent where required. Use fictional or consenting adults for tests. Standard mode excludes training but is not zero retention. Every briefing discloses AI uncertainty. [Privacy notice](docs/privacy.md).

The earlier `pi_pipeline.py` and `computer_receiver.py` remain legacy references and do not satisfy the new service's security/privacy requirements. Their [old README](docs/legacy-prototype.md) is preserved. The pre-existing résumé is unused; `.gitignore` cannot remove data already tracked in Git history.
