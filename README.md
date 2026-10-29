# otlp-trace-shape

[![tests](https://github.com/maomao-1937/otlp-trace-shape/actions/workflows/tests.yml/badge.svg)](https://github.com/maomao-1937/otlp-trace-shape/actions/workflows/tests.yml)

Check the parent graph in one saved OTLP/JSON trace export, without a Collector or trace backend. This Python 3.11 standard-library CLI reports duplicate span identities, parent cycles, self-parent references, reversed timestamps, and missing-parent counts.

Missing parents are information by default: an export can be partial or sampled. Use `--require-parents` only when your capture is expected to contain every parent. A clean result says only that the supported checks found no findings in this input.

## Install and run

Requires Python 3.11 or newer. Download or clone the repository, then run the source directly. There is no `pip install`, third-party dependency, service, account, network call, or child process in the CLI.

```console
python otlp_trace_shape.py examples/clean.json
```

Actual output:

```text
clean: resourceSpans=1 scopeSpans=1 spans=2 uniqueSpans=2 traces=1 roots=1 parentEdges=1 missingParents=0
```

Read a saved UTF-8 request file or use `-` (also the default) for standard input:

```console
python otlp_trace_shape.py examples/partial.json --json
python otlp_trace_shape.py examples/partial.json --require-parents --json
python otlp_trace_shape.py - --json < examples/clean.json
```

The last command uses POSIX shell or Windows cmd redirection. In PowerShell, use `Get-Content -Raw examples/clean.json | python otlp_trace_shape.py - --json` for this ASCII fixture; use a file argument for arbitrary UTF-8 telemetry.

The first partial-input command prints this JSON and exits 0:

```json
{"counts":{"missingParents":1,"parentEdges":0,"resourceSpans":1,"roots":0,"scopeSpans":1,"spans":1,"traces":1,"uniqueSpans":1},"findings":[],"information":[{"code":"missing_parent","spanIndex":0}],"schemaVersion":1,"status":"clean"}
```

Adding `--require-parents` moves that record into `findings`, sets `status` to `findings`, and exits 1. Indexes are zero-based in resource/scope/span array traversal order; use them to locate records locally.

## Supported input and checks

Input is exactly one JSON object shaped as an OTLP `ExportTraceServiceRequest`: `resourceSpans[] → scopeSpans[] → spans[]`. `{}` and omitted/empty repeated arrays are accepted as empty evidence. An empty result explicitly includes `empty_input`, `spans: 0`, and `traces: 0`. It does not establish coverage of your application or pipeline.

Example span inside those arrays:

```json
{"traceId":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","spanId":"0000000000000001","startTimeUnixNano":"10","endTimeUnixNano":"20"}
```

- Trace IDs must be 32 hex characters; span IDs and nonempty parent IDs must be 16. All must be nonzero. Case is normalized before comparisons.
- An absent or empty `parentSpanId` means root. This tool rejects an all-zero parent ID, rather than treating it as a root alias: the proto specifies an empty parent for roots. This is an explicit input policy.
- Identity is the pair `(traceId, spanId)`. Reusing a span ID in another trace is legal. Parent lookup stays within the trace and crosses resource/scope groups in this one input.
- Duplicate identities produce `duplicate_span`. Graph counts and parent traversal use the first occurrence; all duplicate records still have their timestamp and ID fields checked. No repair or merging occurs.
- `self_parent`, `parent_cycle`, and `time_order` are findings. Each multi-node cycle is reported once with sorted `spanIndexes`. No child/parent time containment is required.
- Both timestamps are required by this tool. They accept unsigned decimal strings of 1–20 digits or JSON integer tokens, from 0 through 18446744073709551615. Signs and whitespace are prohibited inside quoted decimal strings. Numeric JSON `-0` normalizes to 0 and is accepted; negative values, booleans, floats, exponent forms, and missing timestamps are rejected. This is a deliberately narrower numeric syntax than a general protobuf JSON decoder.
- Structural arrays must be arrays of objects. Optional resource/scope metadata must be objects; attributes/events/links containers, when inspected, must be arrays of objects. Attribute values, names, status, events, links, enum semantics, schema URLs, and resource semantics are not fully validated. Unknown fields are otherwise ignored.

Flat spans, Jaeger JSON, JSONL/multiple requests, binary protobuf, compressed input, snake-case wrappers, and legacy `instrumentationLibrarySpans` are unsupported. Convert them to the documented request shape separately. The tool is a graph checker for a stated subset, not an OTLP receiver or a full OTLP conformance validator.

## Configuration and limits

All configuration is through flags; there are no environment variables or configuration files.

| Flag | Default | Allowed range | Meaning |
| --- | ---: | ---: | --- |
| `--max-bytes` | 10485760 | 1–1073741824 | UTF-8 input bytes, including whitespace |
| `--max-depth` | 64 | 1–256 | Nested JSON containers, root object has depth 1 |
| `--max-spans` | 100000 | 1–1000000 | Span records, including duplicates |
| `--require-parents` | off | switch | Missing parents become findings |
| `--json` | off | switch | Stable compact JSON, schema version 1 |

`--help` and `--version` are also available. For example:

```console
python otlp_trace_shape.py capture.json --json --max-bytes 2097152 --max-depth 32 --max-spans 10000
```

Files/stdin are read up to the byte limit plus one byte. JSON depth is scanned before decoding, including ignored metadata. Duplicate JSON keys anywhere, non-finite numbers (including float overflow), malformed JSON, and invalid UTF-8 are rejected. The document is decoded in memory; limits bound accepted input, not exact process memory. Graph traversal is iterative with linear node/edge work; output grows with the number of findings/information records.

| Exit | Meaning |
| --- | --- |
| 0 | Supported input has no findings; information may still be present |
| 1 | One or more graph/time findings |
| 2 | Invalid/unsupported input, exceeded limit, invalid flags, or I/O failure |

Invalid inputs have no partial counts, so incomplete validation cannot appear clean:

```console
python otlp_trace_shape.py examples/invalid-id.json --json
```

```json
{"error":{"code":"invalid_trace_id"},"schemaVersion":1,"status":"invalid"}
```

Error codes include `invalid_container`, `unsupported_shape`, `invalid_trace_id`, `invalid_span_id`, `invalid_parent_id`, `invalid_timestamp`, `duplicate_json_key`, `invalid_json`, `byte_limit`, `depth_limit`, `span_limit`, `invalid_configuration`, `invalid_cli`, and `input_io`. Output failures return 2 and attempt the generic `output_io` message on stderr, including when `--help` flushes to a closed pipe.

Reports contain fixed codes, counts, and indexes only: no IDs, span names, attribute keys/values, resource values, supplied CLI values, or input paths. Input content is still held locally in memory. For automation use `--json`; human formatting is intended for terminal reading.

## 中文快速开始

需要 Python 3.11 或更新版本，直接运行源码，无需安装依赖：

```console
python otlp_trace_shape.py examples/clean.json
python otlp_trace_shape.py examples/partial.json --require-parents --json
python -m unittest discover -s tests -v
```

只接受单个 OTLP/JSON 请求对象的 `resourceSpans/scopeSpans/spans` 结构。缺失父 span 默认只提示，因为采样或分批导出可能导致父节点不在当前文件中；确认应包含全部父节点时再加 `--require-parents`。重复 ID、环、自指父节点及起止时间倒置返回 1；格式错误、不支持的格式、超限或 I/O 错误返回 2。空输入会明确显示零 span、零 trace，不能说明采集完整。输出只含代码、数量和下标，不打印遥测内容或路径。各项输入限制和边界见上表。

## Validation and scope

Locally verified on Windows with CPython 3.11.15: 39 unittest tests and 10 CLI examples/exit-code checks. See [TESTING.md](TESTING.md) for commands and evidence boundaries and [RESEARCH.md](RESEARCH.md) for motivation, sources, and existing alternatives. Collector/backend integration, live captures, production behavior, other operating systems, and user adoption have not been established by these local tests.

MIT license, copyright 2026 maomao-1937.
