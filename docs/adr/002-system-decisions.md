# System decision records

Each row records context/alternatives, choice and consequence.

| ADR | Context / alternatives | Decision | Consequence |
|---|---|---|---|
| 002 | Arduino vs ESP-IDF | ESP-IDF 5.5, camera 2.1.8 | Explicit memory/TLS/pins; actual toolchain build needed |
| 003 | HTTP/SSE vs WebSocket/MQTT | HTTPS upload, SSE UI, device polling | No broker; reconnect using snapshots |
| 004 | Synchronous vs async | 202 and asyncio jobs | Long research separated from upload; cancellation required |
| 005 | Microservices vs monolith | One process with module boundaries | Simple deployment; no multiple workers |
| 006 | Node vs Python | Python/FastAPI/Pydantic/HTTPX/Pillow | Strong schemas and image tools; venv required |
| 007 | Single prompt vs stages | Classify, extract, research/resolve, synthesize, verify | Inspectable failures; more calls/latency |
| 008 | Custom scraper vs grounding | Provider search/snippets only | No host scraper; provider cost/access dependency |
| 009 | Prose vs schema | Strict schema and citation checks | Malformed output rejected, one repair |
| 010 | Database vs ephemeral | Memory TTL/purge, no profiles | Restart loses results; only device hashes persist |
| 011 | mTLS vs pinned CA/token | CA and hostname verification + per-device token | Physical commissioning and revocation required |
| 012 | Terminal/display vs phone | Static responsive PWA and LED | One origin, no frontend build dependency |

Dependency rationale: FastAPI—HTTP/SSE contracts; Uvicorn—ASGI server; Pydantic—schemas; HTTPX—async network/fixtures; Pillow—JPEG checks; structlog—redacted structured logs; PyYAML—config; cryptography—development certificates. Tests/tooling: pytest and pytest-asyncio—behavioral checks; Ruff—lint/format; mypy—type checks; pip-audit—advisories. Transitive versions pinned in requirements.lock. Firmware uses Espressif's Wi-Fi/TLS/NVS/FreeRTOS components and camera driver.
