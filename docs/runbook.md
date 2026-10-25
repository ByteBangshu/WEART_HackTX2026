# Runbook and demo

Start with `python tools/run.py`; unlock at the printed origin using `runtime/local-config.json`. Default provider is mock. Stop with Ctrl+C. Briefs/cache vanish; device hashes persist. Changes to provider/TLS require restart. Run one Uvicorn worker only.

For a real ESP32 USB capture, follow [USB capture setup](hardware.md#usb-capture-to-the-local-app). The bridge rejects mock mode to avoid returning a fictional person summary.

## Three-minute demo

1. State explicitly whether this is fictional offline simulation or physical/live processing.
2. Trigger camera/simulator/demo. Show extracted professional fields, confidence, source-linked briefing and questions.
3. Expand Why this works and Sources: demonstrate evidence → claim → question.
4. Click Wrong person? Show organization fallback instead of merged identities.
5. Try the rejected-card demo: no extracted personal fields or research.
6. Forget the briefing and show removal from the session list.

## Troubleshooting

| Symptom | Check |
|---|---|
| Firmware safe mode | Exact pins, PSRAM, duplicate GPIOs, confirmation checkbox |
| Connection fails | 2.4 GHz WPA2, client isolation, explicit bind, private firewall access. With UFW, allow TCP 8765 from the device/subnet to the host IP on the Wi-Fi interface. |
| TLS fails | Correct CA, hostname/IP SAN, synchronized clock; never disable validation. If UDP/123 is blocked, firmware falls back to its build timestamp, so that timestamp must still be within the host certificate's validity period. |
| Pairing fails | Code expiry, unique device ID, prior revocation if replacing |
| UI 400/403 | Use exact WEART_ORIGIN, valid session/CSRF |
| 401 | Local passphrase/token, session expiry, registry mismatch |
| Context unavailable | Search opt-in, provider access, absent sources or genuine ambiguity |
| Retakes | Card framing, focus, light and glare; thresholds are heuristic |
| Budget exhaustion | Reserved metrics and provider limits; do not automatically increase caps |
| Async tests hang in restricted Windows executor | asyncio needs local socketpair permission; run in a normal local terminal |

`/healthz` = liveness; `/readyz` = capture readiness; `/metrics` and `/v1/openapi` require UI auth. UI mutations use cookie + `X-CSRF-Token`; device calls use bearer token + `X-Device-ID`, and uploads additionally `X-Capture-ID` and image/jpeg. Never put secrets in URLs. No public tunnel or raw-output logging.
