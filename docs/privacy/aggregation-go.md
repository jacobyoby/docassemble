# Go native-output aggregation

Status: integrated into the candidate's [Go native runner](native-runner-go.md).
**Not deployed.** The separate startup diagnostic does not import this library;
cross-compiling only that executable would not verify the native capture path.

`Docker/privacy-diagnostic/internal/aggregate` uses only the standard library.
It replaces the aggregation algorithm, preserving the reviewed Python draft's
counter semantics. It does not start processes, read descriptors, write logs,
schedule snapshots, or enforce native configuration. The process runner must
provide those boundaries. The candidate launchers now select the Go runner.

## Interface and retained state

Construct an `Aggregator` with `New(Nginx)`, `New(UWsgi)`, `New(Celery)`,
`New(CelerySingle)`, `New(Websockets)`, or `New(Mail)`. Call `Feed` with
`Stdout` or `Stderr`, `Finish` at that stream's EOF, and `Snapshot` for a value
copy. The caller must serialize these operations. Invalid components, streams,
nil receivers, and zero values return fixed errors without mutating state.

Each stream owns one 4,096-byte array. Partial input is copied, so callers may
reuse their read buffer after `Feed` returns. Consumed, overflowing, and finished
owned buffers are cleared. This does not promise erasure of caller buffers,
runtime copies, OS buffers, swap, or core dumps; the runner remains responsible
for its own memory and process protections.

A line may contain at most 4,096 bytes before its newline, including a trailing
carriage return. Overflow increments `dropped` immediately and only once, then
discards input through the next newline. EOF consumes a valid unterminated tail
once. Repeated EOF is harmless; a later feed starts a fresh line. stdout and
stderr never share partial records.

## Accepted records

For nginx/uWSGI request counters, records must contain exactly three space-separated tokens:

```text
PRIVACY_REQUEST status=200 msecs=99
PRIVACY_REQUEST status=503 seconds=30.000
```

Status is exactly three ASCII digits in 100–599. Milliseconds are canonical
unsigned decimal, without leading zeroes except `0`, in 0–600000. Only nginx
accepts seconds: one to three canonical whole digits, a decimal point, and
exactly three fractional digits, with the same upper limit. Extra fields,
embedded CR/NUL, malformed UTF-8, and invalid numeric forms cannot become
request counts. A single trailing CR is accepted. Valid text without the exact
first token increments `unclassified`; malformed marked records increment
`rejected`.

Application profiles count all valid text as `unclassified`, including request
lookalikes. Malformed text and overflow retain the same rejected/dropped rules.
Their status/latency counters always remain zero and serialization rejects
forged nonzero request counters. See [application capture](application-capture-go.md).

Snapshots contain exactly 14 JSON fields: schema `1`, a fixed component, five
status-family counters, four latency counters, `unclassified`, `rejected`, and
`dropped`. Latency buckets are below 100 ms, 100–999 ms, 1000–29999 ms, and
30000–600000 ms. Every counter is cumulative and saturates at 2^31−1.
Serialization rejects forged components, schema values, and oversized counters
before producing output. Raw input never becomes a snapshot field or error.

## Verification

Run from the checkout root:

```sh
bash tests/verify_privacy.sh
```

The command checks all Go packages with formatting, vet, race tests, module
verification, and Linux amd64/arm64 compilation. It runs ten seconds of fuzzing
for each of the startup diagnostic, aggregator, preflight, and monitor, then all 131 native/application-launcher
and 84 frozen application draft tests plus shell syntax and diff whitespace. No production
dependency was added. CI also runs the pinned development scanner
`govulncheck@v1.7.0`; the local aggregator scan found no vulnerabilities.

The Go tests compare 240 deterministic synthetic scenarios with the frozen
Python algorithm in `tests/privacy_native/reference/log_aggregate.py`, including
both streams, arbitrary fragmentation, intermediate
snapshots, and repeated EOF. The test-only oracle lives in
`tests/privacy_native/aggregate_reference.py`. It verifies the reference SHA-256
`582582eacbb29d486e1a9b8205577664d5eb239f85493441970197b53f31951f`.
Boundary and malformed-input tests provide expectations independent of that
reference. A mutation control changing the overflow check from `>` to `>=`
fails specifically because a valid 4,096-byte line is dropped.

Local evidence is in `tests/.aggregate-review/`. The final focused run passed,
including 77,263 aggregate fuzz executions and 974,367 diagnostic executions.
Fuzz debug output attributes long progress pauses to input minimization; no
failure was reported. A separate benchmark processes a 64 KiB oversized line
in one-byte fragments in approximately 0.34 ms on this Apple M4, with zero
allocations. This measures the parser only, not service throughput. Unit tests
also check fixed state size and zero allocations for a 1 MiB oversized chunk.

Remaining release work is recorded in [the release review](review-2026-09-05.md).
The Go runner now connects this library to bounded pipe capture and snapshot
delivery, with Linux process and launcher tests. Full service installation,
complete application output coverage, monitoring, and rollback remain open.
