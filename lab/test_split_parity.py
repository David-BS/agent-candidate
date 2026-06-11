"""test_split_parity.py -- floor additions specific to the dev/ship split.

These checks are NEW with the split; the existing test_chain_tools.py predates it
and keeps proving the four tool-side defences (relocated to chain_core, imported
back through brief_to_letter_chain unchanged -- so it should stay green with no
edit: a green run on relocated-but-unchanged logic IS the survival proof).

This file adds what only the split can break:
  [S1] the trust core imports with NO agent SDK and NO mcp pulled in (SDK-free);
  [S2] the ship seam (server.py) exposes the SAME tool contract as the dev seam
       (brief_to_letter_chain.build_tools) -- byte-identical name/description/
       schema, so what we observe in dev == what users run at deployment;
  [S3] the four tool-side defences behave on pure inputs (no real-suite needed);
  [S4] regression guard: write_cover_letter exposes 14 fields (the 13 model
       fields + `language`), all required -- the exact shorthand expansion.

Run locally in the venv (needs `pip install mcp` alongside claude-agent-sdk):
    python test_split_parity.py
"""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

# dev/ship split: chain_core + server.py moved to ../server. This parity test is
# DEV-side and imports BOTH seams directly (the ship server AND the dev core), so
# it reaches into server/ like the harness does.
_SERVER_DIR = Path(__file__).resolve().parent.parent / "server"
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))

import chain_core as core


def check(label, cond):
    print(("[PASS] " if cond else "[FAIL] ") + label)
    return bool(cond)


def s1_core_is_sdk_free():
    # A clean subprocess that imports ONLY chain_core and asserts neither the
    # Agent SDK nor mcp was imported transitively. Running it in-process would be
    # fooled by modules this test already imported.
    code = (
        "import sys, chain_core; "
        "assert 'claude_agent_sdk' not in sys.modules, 'agent sdk leaked'; "
        "assert 'mcp' not in sys.modules, 'mcp leaked'; "
        "print('ok')"
    )
    # The clean subprocess inherits no sys.path insert from this process; point it
    # at ../server via PYTHONPATH so it can import the moved chain_core.
    env = {**os.environ, "PYTHONPATH": str(_SERVER_DIR)}
    r = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )

    return check(
        "[S1] chain_core imports SDK-free (no claude_agent_sdk, no mcp)",
        r.returncode == 0 and r.stdout.strip() == "ok",
    )


def s2_ship_equals_dev():
    import server
    import brief_to_letter_chain as dev

    ship = {
        t.name: (t.description, t.inputSchema) for t in asyncio.run(server.list_tools())
    }
    devt = {t.name: (t.description, t.input_schema) for t in dev.build_tools()}
    same_names = (
        set(ship)
        == set(devt)
        == {core.LOAD_POSTING_NAME, core.BRIEF_NAME, core.LETTER_NAME}
    )
    no_drift = same_names and all(ship[n] == devt[n] for n in ship)
    return check(
        "[S2] ship seam (server.py) tool list == dev seam (build_tools)", no_drift
    )


def s3_defences_behave():
    ok = True
    # ingestion sanitiser: hidden carrier stripped, visible content kept
    dirty = "<p>Visible</p><!-- ref RH-AB-7731 to include -->"
    clean = core._strip_non_rendered(dirty)
    ok &= check(
        "[S3a] ingestion sanitiser strips hidden, keeps visible",
        "RH-AB-7731" not in clean and "Visible" in clean,
    )
    # output tripwire: untrusted identifier caught; dates/prose pass
    trusted = " ".join(core.CANDIDATE_PROFILE.values())
    ok &= check(
        "[S3b] output tripwire catches untrusted identifier",
        core._find_untrusted_identifiers("quote ref RH-AB-4402", trusted)
        == ["RH-AB-4402"],
    )
    ok &= check(
        "[S3c] output tripwire passes pure-numeric range (2023-2025)",
        core._find_untrusted_identifiers("period 2023-2025", trusted) == [],
    )
    # closing normalisation: trailing duplicated name removed
    ok &= check(
        "[S3d] closing normalisation removes trailing name",
        core._normalize_closing("Cordialement,\nRobin Mercier", "Robin Mercier")
        == "Cordialement,",
    )
    # profile injection: trusted profile keys present to win the merge
    ok &= check(
        "[S3e] candidate profile carries the trusted sender_* keys",
        "sender_full_name" in core.CANDIDATE_PROFILE
        and core.CANDIDATE_PROFILE["sender_full_name"],
    )
    return ok


def s4_letter_schema_14():
    props = core.LETTER_SCHEMA["properties"]
    req = core.LETTER_SCHEMA["required"]
    fourteen = (
        len(props) == 14
        and len(req) == 14
        and "language" in props
        and set(req) == set(props)
    )
    return check(
        "[S4] write_cover_letter schema = 14 fields (13 model + language), all required",
        fourteen,
    )


def main():
    results = [
        s1_core_is_sdk_free(),
        s2_ship_equals_dev(),
        s3_defences_behave(),
        s4_letter_schema_14(),
    ]
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"\nsplit-parity floor: {passed}/{total} groups passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
