# Threat model

Assets: API key, device token, Wi-Fi credentials, raw image, professional fields/evidence, provider spend. Boundaries: card→camera, LAN→host, host→Meta/search, model output→browser.

| Threat | Mitigation | Residual risk |
|---|---|---|
| Spoofed device | Random token, host hash, scoped access, revocation | Physical theft; flash encryption not yet configured |
| Prompt injection | Delimited data, schema constraints, search-only tools, verification | Model behavior remains probabilistic |
| Poisoned source/wrong person | Actual retrieved snippets, name/org checks, independent domains, fallback | Copied bios, common names and publisher reliability assessment need live evaluation |
| LAN MITM/rebinding | TLS CA/hostname validation, private bind, Host/origin checks | Initial CA trust relies on physical commissioning |
| Stolen device | No model keys or retained images; revocable token | Unencrypted NVS readable by a physical attacker |
| Secret leakage | Environment key, ignored runtime, no response/exception logging | OS dumps, shell handling and existing Git history remain operator concerns |
| Cost exhaustion | Rate/concurrency limits, deadlines, reservations, kill switch | Search ceiling unverified; ledger resets on restart; provider controls required |
| Malicious JPEG | Streaming byte cap, predecode pixel cap, decode validation | Keep decoder patched; processing still uses resources |
| Browser injection | Text rendering, CSP, HttpOnly/SameSite session, CSRF | Clipboard actions are explicit; do not cache private responses |
| Retention/late writes | Await cancellation, TTL, cache invalidation | Local release is not secure RAM erase or provider deletion |
| Provisioning abuse | Physical commissioning, random WPA2 setup password, one client | Portal uses HTTP inside protected AP; no auto captive DNS |

No cloud deployment, facial recognition, sensitive profiling, arbitrary host URL fetches or messaging. Prompt filtering is not proof of zero excluded-category leakage. This is not production security certification.
