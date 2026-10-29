# Testing

Local verification: 2026-10-29, Windows, CPython 3.11.15. Uses only the Python standard library. These results precede any remote publishing/CI run.

```console
python -m unittest discover -s tests -v
```

Actual result: **39 tests passed**, exit 0. Tests include real file/stdin subprocess invocations and closed stdout pipe handling during both `--help` and report flushing. The product itself does not create child processes.

Covered behavior:

- Empty evidence/counts; omitted/empty repeated fields; parent lookup across groups and within trace identity; legal shared span IDs across traces; case normalization and duplicate detection.
- Partial input policy, strict parent policy, root encoding, self-parent, multi-node and disjoint cycles, cycle tails, a 3,000-node chain, and per-span ordering without parent-time containment.
- Zero/invalid/wrong-type IDs, uint64 boundaries, booleans/floats/long/negative/signed timestamps, required timestamps, structural and selected metadata containers, unsupported flat/legacy/snake-case wrappers.
- Byte/depth/span boundaries, strings containing structural punctuation, 2,000 nested containers, duplicate JSON keys including ignored data, non-finite numbers including overflow, invalid UTF-8, malformed JSON, and multiple documents.
- Deterministic JSON, exit codes 0/1/2, human output, generic I/O and flag errors, no payload or path echo, and controlled broken-pipe errors.

## Reproduce fixture CLI checks

`checks.json` is a list of `{ "args": [...], "exit": N }` objects. Each `args` starts with the source filename; runners prepend only the Python interpreter. It records 10 actual invocations: eight fixture files, strict partial-parent mode, and help.

```python
import json
import subprocess
import sys
from pathlib import Path

for check in json.loads(Path("checks.json").read_text(encoding="utf-8")):
    result = subprocess.run([sys.executable, *check["args"]], check=False)
    assert result.returncode == check["exit"], check
```

Actual local result: **10/10 expected exit codes matched**. Inputs and representative outputs are in `examples/` and README.

## Test-first evidence

The first test run happened before `otlp_trace_shape.py` existed and recorded `ModuleNotFoundError: No module named 'otlp_trace_shape'` plus missing-source CLI failures. The initial implementation passed 37 tests. A further regression test demonstrated that a snake-case wrapper could otherwise silently appear empty; that test failed before its fix. The final 39-test run passed.

Build-session evidence is retained outside the publishable project at `../../builder-evidence/otlp-trace-shape/`: `tdd-red.txt`, `tdd-green.txt`, `wrapper-red.txt`, `final-tests.txt`, and `cli-checks.json` (interpreter/platform plus exact stdout, stderr, expected and actual exit codes). Those files belong to the batch audit, rather than to the repository's runtime.

## Limits of this evidence

Synthetic local unit/CLI tests do not establish interoperability with a live exporter/backend, successful real-driver reproduction, complete OTLP conformance, real-user usefulness, Linux/macOS behavior, or performance at the configured maximums. The 3,000-span chain checks recursion safety; it is not a throughput benchmark. Timestamp lexical restrictions and rejected null/zero-parent forms are documented policies, not claims that every general protobuf decoder behaves identically.
