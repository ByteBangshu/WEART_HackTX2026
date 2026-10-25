# Prototype privacy notice

Purpose: prepare professional conversations using professional badges/cards and public work-related sources. No face recognition, identity-number extraction, résumé comparison or stored profiles.

Images are decoded with limits, stripped of metadata, held only in application memory, then released after extraction/failure. Results/cache expire after 30 minutes. Forget/purge cancels active work and removes application references; it does not guarantee cryptographic RAM erasure, exclusion from swap/dumps or provider deletion.

Live mode sends a full image to Meta for classification/extraction, then allowed fields for research. The provider can see incidental card contents even though output fields are restricted. Standard mode excludes training. `store:false` is not ZDR; Meta's documented ZDR disables search.

Persistent data: device IDs/token hashes; ignored launcher credentials; operator TLS keys. Browser storage: appearance preference and static app shell only. Logs: job IDs/states/counts/estimates, no intentional personal payloads. No history database.

Test with fictional or consenting adults. Respect local law, including GDPR/CCPA where applicable, and event rules; obtain consent where required. Government/payment cards are unsupported. Do not use briefings for employment eligibility or other high-impact decisions. The UI discloses uncertainty and provider processing. This notice is an implementation description, not legal advice or compliance certification.
