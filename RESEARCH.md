# Research notes

Sources were read on 2026-10-29 for the 2026-10-28 project batch. This project is an original, small offline checker; no external implementation was copied.

## Observations

1. [OTLP specification](https://opentelemetry.io/docs/specs/otlp/) describes the trace export request, case-insensitive hexadecimal IDs, lower-camel-case field names, and decimal-string/number decoding of 64-bit timestamps. This tool supports only the stated JSON request subset and integer-token syntax; it is not a receiver conformance implementation.
2. [Official trace.proto](https://github.com/open-telemetry/opentelemetry-proto/blob/main/opentelemetry/proto/trace/v1/trace.proto) defines resource/scope/span grouping, trace IDs of 16 bytes, span IDs of 8 bytes, invalid zero trace/span IDs, and empty parents for roots. Based on that root representation, this tool deliberately rejects zero-filled parent IDs. It checks ordering within each span, without requiring parent/child temporal containment.
3. [MongoDB DRIVERS-3669](https://jira.mongodb.org/browse/DRIVERS-3669), created October 2, 2026, reports that per-span sampling can leave an exported command span without its operation parent. At read time the ticket was closed as “Works as Designed”, resolved October 26. This is evidence of a reporter's missing-parent concern and relevant sampling context, not an independently reproduced driver bug or proof of a current product defect. This project uses synthetic fixtures and does not run MongoDB drivers.

## Inferences and product decision

A saved capture can contain useful graph evidence even when it cannot establish trace completeness. A local, dependency-free summary can therefore be useful in CI fixtures or before sending a capture to a backend. That usefulness is a product hypothesis, not demonstrated demand or adoption. Missing parents are information unless the operator explicitly requires them. Indexed findings avoid printing telemetry values while still identifying records in the local input.

No source above establishes a need for this specific CLI, and no claim is made about stars, usage, full OTLP coverage, or unique capability.

## Existing alternatives

- [OpenTelemetry Collector troubleshooting](https://opentelemetry.io/docs/collector/troubleshooting/) recommends local exporters, including the debug exporter, to inspect data moving through a Collector. This is a better fit for diagnosing a live telemetry pipeline. This CLI instead reads one saved request and returns a bounded indexed graph summary; it does not claim the Collector lacks graph diagnostics.
- [Jaeger architecture](https://www.jaegertracing.io/docs/2.22/architecture/) describes ingestion, storage, query APIs, and a UI for visualizing traces. Jaeger is a better fit for interactive trace investigation and retained data. This CLI offers a much narrower offline check and is not a Jaeger replacement. No exhaustive comparison of backend validation features was performed.

## Unverified

There are no live Collector/MongoDB/Jaeger integrations, production captures, user interviews, performance benchmarks at the maximum limits, or deployment results in this repository. Limits are guardrails rather than a benchmark claim.
