# ADR-001 — Meta Model API

Status: implemented against documentation; live account compatibility unverified. Reviewed 2026-10-25.

Context: image extraction, typed outputs and professional search evidence. Options: direct Meta, aggregator, or mock-only. Decision: direct Meta behind the Provider port, with a deterministic fictional mock for offline work.

| Contract | Verified selection |
|---|---|
| Endpoint | POST `https://api.meta.ai/v1/responses` |
| Auth | Bearer `MODEL_API_KEY` |
| Model | `muse-spark-1.3` Standard; configurable Standard 1.2/1.1 |
| Image | `input_image`, base64 JPEG `image_url`, no Files API |
| Storage | `store:false`; not account-level ZDR |
| Output | `text.format`, `json_schema`, schema/name, `strict:true` |
| Schema | Object root, all properties required, no additional properties, nullable unknowns |
| Reasoning | `reasoning.effort`: low for classify/extract, medium later |
| Tokens | `max_output_tokens:4000`, including reasoning |
| Search | `web_search`, medium context; `include:["web_search_call.results"]` |
| Grounding | Model URLs alone are insufficient; actual retrieved snippets must match |
| Limits | Standard Spark 1.3: 3,000 RPM and 4M TPM per team |
| Prices | $1.25/M input, $0.15/M cached input, $4.25/M output; $2.50/1,000 search queries |
| Image limit | Provider 50 MB inline; app 10 MB and 50 MP before downsampling |
| Region | Expanded availability; local account access still needs verification |

Sources: [Responses](https://dev.meta.ai/docs/protocols/responses), [models](https://dev.meta.ai/docs/models), [images](https://dev.meta.ai/docs/image-understanding), [schemas](https://dev.meta.ai/docs/structured-output), [search](https://dev.meta.ai/docs/search-grounding), [reasoning](https://dev.meta.ai/docs/reasoning), [pricing](https://dev.meta.ai/docs/pricing-rate-limits), [availability](https://dev.meta.ai/help/accounts-and-login/supported-countries).

Standard mode excludes training; Contributor IDs are rejected. Separate ZDR enablement disables web search, so this design cannot promise both. [ZDR restrictions](https://dev.meta.ai/help/policies-and-privacy/zero-data-retention).

Consequences:

- No side-effect tools. Two attempts per stage call, jitter, deadlines and circuit breaker. Invalid structured data fails closed.
- Stable prompt prefixes permit provider-managed caching; no undocumented cache-control parameter is invented.
- Token usage and observed search-call counts are recorded without payload logs. Estimates omit cached-input discounts and may not equal billed queries.
- No verified hard provider-side query cap exists in the reviewed contract. Live search defaults off. Enabling it accepts potential cost beyond local reservations. Image/search tokenization is variable; request reservations are admission controls, not exact billing bounds. Daily ledger resets on process restart.
- Live search+schema compatibility, refusal/truncation behavior, real OCR, source quality and latency require account tests. MockTransport tests validate our request shape only.
