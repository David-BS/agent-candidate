"""Floor guards for family c1 -- candidate identity binding (MCP path).

Falsify-first: these guards are written to FAIL against the current code and to
turn green only once the fix lands. They encode the c1 Definition of Done:

  * STRUCTURAL GATE -- ``candidate_name`` is ABSENT from the MCP input schema of
    the four tools that expose it (the free identity channel is removed), AND the
    wrapper injects it from ``CANDIDATE_PROFILE`` (manifest promise true by
    construction). We remove the channel; we do not scan symptoms.
  * The channel is the single discrete identity field ``candidate_name``, present
    identically on the four md-generators -- strategic_playbook,
    application_summary, interview_prep, quick_reference. cover_letter is already
    bound (sender_* injected from the profile, absent from its schema), so it is a
    VERIFICATION here, not a change (see test_cover_letter_already_bound).

The free-text career/analysis dimension (pain_points, pitch, ...) is an
UNDECIDABLE channel -- out of scope for this structural floor; it is a candidate
follow-up family, decided on evidence via the negative-sanity observation.
"""

import json
import sys
import tempfile
import types
from pathlib import Path

# Resolve chain_core the same way the lab floor does (server/ is a sibling of lab/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
import chain_core as core  # noqa: E402

# The fictional identity the wrapper must inject (the frozen project decision).
FICTIONAL_NAME = "Robin Mercier"
# A stand-in for a real identity that must NEVER survive into the payload. If a
# caller supplies this, injection must override it with FICTIONAL_NAME.
SENTINEL_REAL = "Sentinel Realname Doe"

# The four tools that expose candidate_name as a free input field.
IDENTITY_TOOL_SCHEMAS = {
    core.PLAYBOOK_NAME: core.PLAYBOOK_SCHEMA,
    core.SUMMARY_NAME: core.SUMMARY_SCHEMA,
    core.INTERVIEW_NAME: core.INTERVIEW_SCHEMA,
    core.REFCARD_NAME: core.REFCARD_SCHEMA,
}
IDENTITY_BUILDERS = {
    core.PLAYBOOK_NAME: core.build_playbook,
    core.SUMMARY_NAME: core.build_summary,
    core.INTERVIEW_NAME: core.build_interview,
    core.REFCARD_NAME: core.build_refcard,
}

# Minimal legitimate TARGET fields (these stay free -- user supplied).
_TARGET_DATA = {
    "job_title": "Staff Engineer",
    "company_name": "Globex",
    "date": "2026-06-28",
    "language": "en",
}


def _capture_payload(build_fn):
    """Call a build_* function with a sentinel candidate_name and capture the
    --data-json payload, WITHOUT running the real candidate-suite generator.

    resolve_suite_paths and subprocess.run are stubbed; the build function still
    composes the payload exactly as in production, which is what we inspect.
    """
    captured = {}
    orig_resolve = core.resolve_suite_paths
    orig_run = core.subprocess.run

    def fake_resolve():
        dummy = Path("/nonexistent/candidate-suite/script.py")
        keys = (
            "fill_script",
            "template",
            "brief_script",
            "playbook_script",
            "summary_script",
            "interview_script",
            "refcard_script",
        )
        return {k: dummy for k in keys}

    def fake_run(cmd, **kwargs):
        i = cmd.index("--data-json")
        captured["payload"] = json.loads(cmd[i + 1])
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    core.resolve_suite_paths = fake_resolve
    core.subprocess.run = fake_run
    try:
        with tempfile.TemporaryDirectory() as td:
            data = dict(_TARGET_DATA, candidate_name=SENTINEL_REAL)
            build_fn(data, output_dir=td)
    finally:
        core.resolve_suite_paths = orig_resolve
        core.subprocess.run = orig_run
    return captured.get("payload", {})


def test_candidate_name_absent_from_schema():
    """STRUCTURAL GATE (channel removed): candidate_name must not appear on the
    MCP input surface of the four generators. RED today -- it is present."""
    failures = []
    for tool, schema in IDENTITY_TOOL_SCHEMAS.items():
        if "candidate_name" in schema.get("properties", {}):
            failures.append(
                f"{tool}: 'candidate_name' in inputSchema.properties (free channel open)"
            )
        if "candidate_name" in schema.get("required", []):
            failures.append(f"{tool}: 'candidate_name' in inputSchema.required")
    assert not failures, (
        "candidate_name still on the MCP tool surface:\n  " + "\n  ".join(failures)
    )


def test_candidate_name_injected_from_profile():
    """STRUCTURAL GATE (binding): the composed payload must carry the fictional
    profile name regardless of caller input. RED today -- the caller's value
    passes through unbound (no profile override)."""
    failures = []
    for tool, build_fn in IDENTITY_BUILDERS.items():
        payload = _capture_payload(build_fn)
        got = payload.get("candidate_name")
        if got != FICTIONAL_NAME:
            failures.append(
                f"{tool}: payload candidate_name = {got!r}, expected {FICTIONAL_NAME!r} (not injected)"
            )
    assert not failures, (
        "candidate_name not injected from CANDIDATE_PROFILE:\n  "
        + "\n  ".join(failures)
    )


def test_cover_letter_already_bound():
    """VERIFICATION (green today): cover_letter is already correct -- sender_*
    injected from the profile and absent from its schema. Guards against a
    regression of the existing binding."""
    leaked = [
        k for k in core.LETTER_SCHEMA.get("properties", {}) if k.startswith("sender_")
    ]
    assert not leaked, f"sender_* leaked onto cover_letter surface: {leaked}"
    missing = [
        k
        for k in ("sender_full_name", "sender_email")
        if k not in core.CANDIDATE_PROFILE
    ]
    assert not missing, f"CANDIDATE_PROFILE missing sender fields: {missing}"


if __name__ == "__main__":
    _tests = [
        test_candidate_name_absent_from_schema,
        test_candidate_name_injected_from_profile,
        test_cover_letter_already_bound,
    ]
    red = 0
    for _t in _tests:
        try:
            _t()
            print(f"[PASS] {_t.__name__}")
        except AssertionError as exc:
            red += 1
            print(
                f"[FAIL] {_t.__name__}\n        " + str(exc).replace("\n", "\n        ")
            )
    print(
        f"\n{red} guard(s) RED / {len(_tests)} total "
        "(falsify-first: candidate_name guards are EXPECTED red until the fix lands)"
    )
    sys.exit(1 if red else 0)
