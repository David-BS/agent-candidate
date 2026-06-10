"""
aggregate_runs.py -- read-only aggregate reader over runs/runs.jsonl.

DEV-side analytics, not part of the shipped agent. The MCP server never sees
this ledger (the client owns the loop); aggregate_runs consumes the harness's
RunRecord telemetry produced by brief_to_letter_chain. It therefore lives in
the dev bucket, exactly like the floor and the fixtures -- it is a CONSUMER of
the ledger, not a tool, and it imports nothing from the agent module.

Shape: a pure transform `aggregate(records) -> Aggregates` (no I/O, proven at
the floor on forged lines, promotable without a paid run) wrapped by a thin
read layer `load_ledger(path)` that tolerates a heterogeneous, append-only,
hand-edited-over-time ledger.

Two independent heterogeneity axes the ledger really carries:
  1. Attribution. Old 16-key lines predate run_context/model_requested/
     models_used; new 19-key lines carry them -- but a 19-key line may still
     have run_context = null. So "attributed" is a VALUE test (run_context is a
     non-empty string), never a key-presence test: absent AND null both fall to
     the unattributed bucket.
  2. Tokens. The four token fields are `int | None`: a line may carry the key
     with a null value (usage was absent upstream). A real 0 (cold cache_read)
     is DATA and must count toward the mix; a null is a HOLE and must not.
     None != 0, mirroring None != {} one level up.

Hygiene: the reader touches only metadata keys. ResultMessage's content-bearing
fields (`result`, `structured_output`) were never projected into the ledger; if
a malformed line carried one, the reader still never reads it.

Currency: USD is native (total_cost_usd). The roadmap budget ceiling is in EUR;
no FX rate is frozen here -- the report prints USD and reminds the reader to
convert mentally. Output is ASCII-only (Phase 1 cp1252 console lesson).

    python aggregate_runs.py [path/to/runs.jsonl]
"""

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_LEDGER = Path(__file__).resolve().parent / "runs" / "runs.jsonl"

UNATTRIBUTED = "(unattributed)"

_TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def _is_int(v):
    # bool is an int subclass; a flag must never masquerade as a token count.
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _mean(values):
    return sum(values) / len(values) if values else None


@dataclass
class ScenarioAgg:
    """Per-scenario slice, keyed on run_context (or UNATTRIBUTED)."""

    label: str
    n: int
    n_success: int
    n_error: int
    burn_usd: float          # raw sum; rounded only at display time
    n_cost_present: int
    mean_cost_usd: float | None
    mean_turns: float | None


@dataclass
class Aggregates:
    """Whole-ledger rollup. Raw numbers; formatting rounds for display."""

    n_total: int
    n_success: int
    n_error: int
    # Burn (USD native).
    burn_usd: float
    n_cost_present: int
    n_cost_missing: int
    # Token mix (only over token-complete lines).
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    n_token_complete: int
    n_token_unavailable: int
    reuse_rate: float | None     # cache_read / (cache_read + cache_creation)
    # Latency, captured raw -- pair semantics deliberately unpinned, no overhead.
    mean_duration_ms: float | None
    mean_duration_api_ms: float | None
    n_latency_present: int
    # Per-scenario ventilation (includes the unattributed bucket).
    by_scenario: list = field(default_factory=list)


def aggregate(records):
    """Pure transform: a list of ledger dicts -> Aggregates. No I/O.

    Reads metadata keys defensively via .get(); never assumes a key is present,
    never coerces a null into a zero, never reads a content field."""
    n_success = n_error = 0
    burn = 0.0
    n_cost_present = n_cost_missing = 0
    in_tok = out_tok = cc_tok = cr_tok = 0
    n_tok_complete = n_tok_unavail = 0
    dur_ms = []
    dur_api = []
    scen = {}

    for r in records:
        is_err = bool(r.get("is_error"))
        if is_err:
            n_error += 1
        else:
            n_success += 1

        cost = r.get("total_cost_usd")
        has_cost = _is_num(cost)
        if has_cost:
            burn += cost
            n_cost_present += 1
        else:
            n_cost_missing += 1

        # A line joins the token mix only if ALL four fields are real ints.
        toks = [r.get(k) for k in _TOKEN_KEYS]
        if all(_is_int(t) for t in toks):
            i, o, cc, cr = toks
            in_tok += i
            out_tok += o
            cc_tok += cc
            cr_tok += cr
            n_tok_complete += 1
        else:
            n_tok_unavail += 1

        dm = r.get("duration_ms")
        da = r.get("duration_api_ms")
        if _is_int(dm):
            dur_ms.append(dm)
        if _is_int(da):
            dur_api.append(da)

        # Attribution by VALUE: absent or null run_context -> unattributed.
        label = r.get("run_context") or UNATTRIBUTED
        acc = scen.setdefault(
            label,
            {"n": 0, "s": 0, "e": 0, "burn": 0.0, "cp": 0, "costs": [], "turns": []},
        )
        acc["n"] += 1
        if is_err:
            acc["e"] += 1
        else:
            acc["s"] += 1
        if has_cost:
            acc["burn"] += cost
            acc["cp"] += 1
            acc["costs"].append(cost)
        nt = r.get("num_turns")
        if _is_int(nt):
            acc["turns"].append(nt)

    by_scenario = [
        ScenarioAgg(
            label=lbl,
            n=a["n"],
            n_success=a["s"],
            n_error=a["e"],
            burn_usd=a["burn"],
            n_cost_present=a["cp"],
            mean_cost_usd=_mean(a["costs"]),
            mean_turns=_mean(a["turns"]),
        )
        for lbl, a in sorted(scen.items())
    ]

    denom = cr_tok + cc_tok
    reuse = (cr_tok / denom) if denom > 0 else None

    return Aggregates(
        n_total=len(records),
        n_success=n_success,
        n_error=n_error,
        burn_usd=burn,
        n_cost_present=n_cost_present,
        n_cost_missing=n_cost_missing,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cache_creation_tokens=cc_tok,
        cache_read_tokens=cr_tok,
        n_token_complete=n_tok_complete,
        n_token_unavailable=n_tok_unavail,
        reuse_rate=reuse,
        mean_duration_ms=_mean(dur_ms),
        mean_duration_api_ms=_mean(dur_api),
        n_latency_present=len(dur_ms),
        by_scenario=by_scenario,
    )


def load_ledger(path):
    """Read a JSONL ledger -> (records, n_malformed). Tolerant by design:
    blank lines are skipped, a malformed line is counted and skipped (never
    crashes the read). Returns ([], 0) for a missing/empty ledger."""
    p = Path(path)
    if not p.exists():
        return [], 0
    records = []
    malformed = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if isinstance(obj, dict):
            records.append(obj)
        else:
            malformed += 1
    return records, malformed


# --- formatting (ASCII-only) --------------------------------------------------

def _usd(v):
    return "n/a" if v is None else "$%.6f" % v


def _f1(v):
    return "n/a" if v is None else "%.1f" % v


def _pct(v):
    return "n/a" if v is None else "%.1f%%" % (v * 100)


def format_report(agg, n_malformed=0, source=""):
    out = []
    if source:
        out.append("Ledger: " + str(source))
    line = "Runs read: " + str(agg.n_total)
    if n_malformed:
        line += "  (+%d malformed line(s) skipped)" % n_malformed
    out.append(line)
    if agg.n_total == 0:
        out.append("")
        out.append("Empty ledger -- nothing to aggregate yet.")
        return "\n".join(out)

    out.append("")
    out.append("Outcome")
    out.append("  success %d   error %d" % (agg.n_success, agg.n_error))

    out.append("")
    out.append("Burn (USD native)")
    burn_line = "  total: %s  over %d priced run(s)" % (_usd(agg.burn_usd), agg.n_cost_present)
    if agg.n_cost_missing:
        burn_line += "  (%d without cost)" % agg.n_cost_missing
    out.append(burn_line)
    out.append("  budget ceiling (roadmap s3): ~100-200 EUR / 1-2 months "
               "-- no frozen FX rate, convert mentally")

    out.append("")
    out.append("Burn by scenario")
    for s in agg.by_scenario:
        out.append("  %-28s n=%-3d burn=%s  mean/run=%s  turns~%s  (%d ok / %d err)"
                   % (s.label, s.n, _usd(s.burn_usd), _usd(s.mean_cost_usd),
                      _f1(s.mean_turns), s.n_success, s.n_error))

    out.append("")
    out.append("Tokens (over %d token-complete run(s); %d without token data)"
               % (agg.n_token_complete, agg.n_token_unavailable))
    out.append("  input %d  output %d  cache-creation %d  cache-read %d"
               % (agg.input_tokens, agg.output_tokens,
                  agg.cache_creation_tokens, agg.cache_read_tokens))
    out.append("  warm-cache reuse: %s   (cache-read / (cache-read + cache-creation))"
               % _pct(agg.reuse_rate))

    out.append("")
    out.append("Latency (raw, captured without interpretation)")
    out.append("  mean wall (duration_ms):     %s ms" % _f1(agg.mean_duration_ms))
    out.append("  mean api  (duration_api_ms): %s ms" % _f1(agg.mean_duration_api_ms))
    out.append("  note: pair semantics unpinned; a live run showed api > wall "
               "-- no overhead derived")

    return "\n".join(out)


def main(argv):
    path = argv[1] if len(argv) > 1 else DEFAULT_LEDGER
    records, malformed = load_ledger(path)
    agg = aggregate(records)
    print(format_report(agg, n_malformed=malformed, source=path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
