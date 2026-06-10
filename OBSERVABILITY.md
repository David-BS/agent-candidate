# Observability — collected indicators

What `agent-candidate` records about each run, and how to read it.

This is **development-side** telemetry. The harness emits a `ResultMessage` at the
end of every agent run; `record_from_result` projects it into a **RunRecord** and
`append_jsonl` writes one line to `runs/runs.jsonl`. The aggregate reader
(`aggregate_runs.py`) rolls those lines up into a readable report.

> At deployment the picture changes: the **client** owns the agent loop and this
> `ResultMessage` telemetry, so the MCP server never sees `num_turns` or
> `total_cost_usd`. The *pattern* (project a result -> append JSONL -> aggregate)
> is portable; its current *source* is not. Tool-side observability (which tool
> ran, sanitised inputs, `is_error`, a tripwire firing) is a separate,
> server-side concern.

---

## 1. Where it lives

- **Ledger:** `runs/runs.jsonl` — append-only, one JSON object per line,
  git-ignored (it is local evidence, not source).
- **Content is never recorded.** The `ResultMessage` carries the produced letter
  (`result`) and `structured_output`; neither is projected. A log that captured
  the letter body would become a PII sink at deployment ("letter as exfiltration
  channel" relocated to a file on disk). Every recorded field is metadata.
- The ledger is **heterogeneous and read at `.get()`**: older lines have 16 keys
  (pre-attribution); newer lines have 19. Readers tolerate both.

---

## 2. The ledger line (RunRecord fields)

Each line is metadata only. Nullable fields are marked; `None` (absent upstream)
is kept distinct from a real `0` and from an empty list `[]`.

| Field | Meaning | Notes |
|---|---|---|
| `timestamp` | Local wall-clock when the line was written | IANA zone, real clock; never hand-typed |
| `session_id` | SDK session identifier | |
| `subtype` | Run outcome subtype | e.g. `success`, `error_max_turns` |
| `is_error` | Did the run end in error? | drives the success/error split |
| `stop_reason` | Why the model stopped | `end_turn`, `tool_use`, ... (nullable) |
| `num_turns` | Loop turns the run took | |
| `errors` | Error strings, verbatim | `null` when none |
| `permission_denials` | **Count** of denied tool calls | count only; allow-list makes denials ~never fire |
| `api_error_status` | API error status code | nullable |
| `total_cost_usd` | Run cost, **USD** | nullable (missing usage) |
| `duration_ms` | Wall-clock duration | captured raw — see latency caveat |
| `duration_api_ms` | Summed API call duration | captured raw — can exceed wall |
| `input_tokens` | Fresh input tokens | nullable |
| `output_tokens` | Output tokens | nullable |
| `cache_creation_input_tokens` | Tokens written to prompt cache | nullable |
| `cache_read_input_tokens` | Tokens served from prompt cache | nullable; a real `0` means cold start |
| `run_context` | Scenario label (attribution) | config provenance; defaults to fixture stem |
| `model_requested` | The model we **asked** for | config provenance (`options.model`) |
| `models_used` | Models that actually **ran** | upstream provenance; `null` if absent, `[]` if empty |

`model_requested` (intent) versus `models_used` (reality) is deliberate: it is
their **gap** that informs — utility models running alongside the requested one
show up in `models_used`.

---

## 3. The aggregate report

Run it against the ledger:

```bash
python aggregate_runs.py [path/to/runs.jsonl]
```

The report is plain ASCII (safe on legacy `cp1252` consoles). Indicators:

**Runs read** — total parsed lines, plus a count of blank/malformed lines that
were skipped (the read never crashes on a bad line).

**Outcome** — success versus error counts (`is_error`).

**Burn (USD native)** — total cost summed over **priced** runs (lines with a
non-null `total_cost_usd`); lines without a cost are reported separately, not
counted as zero. Cost is shown in **USD, the native unit**; no exchange rate is
applied.

**Burn by scenario** — the same burn, ventilated per `run_context`, with per-
scenario mean cost per run, mean turns, and ok/err counts. This is the headline
view: the cost deltas that actually mean something (e.g. allow-list halving cost,
a deliberating run costing more) are **per scenario**, which is exactly what
attribution unlocks. Lines without a scenario fall into an `(unattributed)`
bucket (see §4).

**Tokens** — over the **token-complete** runs only (lines where all four token
fields are real integers): summed input, output, cache-creation, cache-read, and
a **warm-cache reuse** rate = `cache_read / (cache_read + cache_creation)`. A
cold-start ledger reads 0%. Lines missing any token field are counted as "tokens
unavailable" and excluded from the mix.

**Latency** — mean wall (`duration_ms`) and mean API (`duration_api_ms`),
**captured raw, with no overhead derived**. See the caveat below.

---

## 4. How to read it — caveats

- **`None` is not `0`.** A real `0` (e.g. a cold `cache_read`) is data and counts
  toward the mix; a `null`/absent field is a hole and is excluded. The same holds
  for `models_used`: `null` means the model-usage map was absent upstream, `[]`
  means it was present but empty.

- **Attribution is a value test, not a key test.** A line counts as attributed
  only when `run_context` is a non-empty string. A 19-key line whose
  `run_context` is `null` is still **unattributed** — absence and null both land
  in the `(unattributed)` bucket.

- **Latency semantics are not pinned.** A live run showed `duration_api_ms`
  (summed API time) **greater than** `duration_ms` (wall) — so "total >= API,
  the gap is overhead" is empirically false here. The reader therefore reports
  both numbers raw and derives nothing. Confirming the sum-vs-wall reading needs
  a multi-model run (parallel calls), where `models_used` becomes the sensor.

- **Reuse rate is a cache-warmth ratio**, not a hit rate against all input:
  `cache_read / (cache_read + cache_creation)`. With no token-complete line it is
  reported as `n/a`, never a fake 0%.

- **`permission_denials` is a count**, not a list of which tools were denied.

- **The reader is currently prospective.** Until attributed runs accumulate, the
  per-scenario view has little to show. Note the split between *building* and
  *using*: the transform is proven deterministically regardless of ledger volume;
  only its diagnostic value grows as runs land.

---

## 5. What is deliberately NOT here

- **No message content** — `result` and `structured_output` are never read.
- **No probability matrix / risk scoring** — this is descriptive telemetry; the
  risk analysis lives in `THREAT_MODEL.md`.
- **No derived latency overhead** — captured, not interpreted (see §4).
- **No frozen FX rate** — cost is USD native by design.
