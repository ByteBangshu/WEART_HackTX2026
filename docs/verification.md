# Verification record

2026-10-25, Windows/Python 3.13.9.

Passed during implementation:

- 38 host behavior/contract/adversarial tests; fake provider transport, no paid API calls. Includes simultaneous upload retries, budget preservation and persistent token revocation.
- Three original legacy tests passed at baseline.
- Ruff checks/formatting; mypy across host package; JavaScript syntax checks.
- 72 fictional JPEG fixtures through offline image-quality evaluation; ten advisory quality warnings. Warnings no longer block extraction.
- Real loopback simulator JPEG upload → host → mock briefing; repeated capture ID deduplication.
- Dependency audit: no known vulnerabilities reported at check time.
- Browser sign-in, automatic device-result display, sourced mock briefing, Wrong person → organization-only, and forgetting. Desktop/mobile and dark mode inspected; no horizontal overflow or browser console errors. Browser inspection predates the current relaxed capture-flow change.
- Local CA/host certificate generation smoke test.

The relaxed capture-flow tests passed: 38 host tests, Ruff and mypy. The separate USB capture test module was not run in this environment because `pyserial` is absent from the local virtual environment. Not established: live Meta compatibility, OCR accuracy, excluded-category recall, false-match rate, real costs/latency; full accessibility audit or security certification. Firmware compilation and physical validation were stopped at the user's request; source is retained. The official build-container download was cancelled before compilation.

Foundations run end to end. Extraction/research code and tests exist, with live acceptance open. Firmware source exists with safe unset pins, with compilation/hardware acceptance open. Hardening remains partial where provider hard search-cost limits and physical protections are unverified. Stretch features are deferred. Do not mark every master-prompt acceptance criterion met from mock tests.
