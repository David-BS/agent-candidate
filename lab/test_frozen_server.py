"""test_frozen_server.py -- exercise the frozen binary AS AN MCP SERVER.

WHY THIS EXISTS (the gap it closes)
-----------------------------------
The frozen win-x64 binary has TWO roles:
  1. `<binary> --run brief|letter ...`  -> self-re-exec into candidate-suite.
     PROVEN by test_frozen_build.py (F1-F4 on the real exe).
  2. `<binary>` (no --run)              -> start the MCP server: enter the stdio
     loop and speak JSON-RPC (initialize / tools/list / tools/call).
     NEVER exercised on the frozen binary. The argv switch (dispatch_suite_run)
     exits BEFORE server init when --run is present, so test_frozen_build's
     coverage stops short of role 2 by construction.

Role 2 is the actual deployment path: Claude Desktop spawns the binary and IS
the MCP client. This smoke test puts a real MCP client (the official `mcp` SDK
client -- the same protocol family the server is built on) in front of the
frozen exe and walks the handshake end to end. It is the cheap, mono-platform
de-risking step that must pass BEFORE the OS matrix / release.yml family
replicates the binary across platforms.

PROOF CATEGORY: execution of the artifact (the binary), like test_frozen_build.
No model, no API, no tokens -- a deterministic local handshake.

WHAT IT HUNTS (frozen-only surprises)
  - asyncio/anyio event loop under PyInstaller (Windows ProactorEventLoop);
  - stdio framing / buffering / stdout pollution on the frozen binary (a HANG or
    a corrupted JSON-RPC stream -> every step is time-bounded, and the server's
    OWN stderr is captured and dumped on failure: a boot crash leaves its
    traceback THERE);
  - spawning the self-re-exec child from inside the async server (T3/T4).

REPORTING: each tier prints the moment it passes (so a mid-run failure shows how
far we got). On error, the anyio TaskGroup ExceptionGroup is unwrapped to its
leaf exceptions, and the frozen server's captured stderr is printed verbatim.

TIERS (degrade gracefully; later tiers need more setup)
  T0  boot + initialize handshake            (binary only)
  T1  tools/list == single-source contract == manifest   (binary only)
  T2  tools/call load_job_posting            (binary only; in-process tool, also
                                              proves the ingestion sanitiser runs
                                              INSIDE the frozen server)
  T3  tools/call generate_posting_brief      (needs CANDIDATE_SUITE_DIR; the
                                              JSON-RPC -> server -> self-re-exec
                                              -> candidate-suite -> .md path)
  T4  refusal contract over the wire         (needs CANDIDATE_SUITE_DIR; a blank
                                              critical field -> isError true)

write_cover_letter over JSON-RPC (.docx through the server seam) is a NAMED
RESIDUE: test_frozen_build F3 already proves .docx-in-frozen via --run.

Single-source discipline: tool NAMES, result PREFIXES and label KEYS come from
chain_core (imported); only fixture VALUES are local.

USAGE
  python lab/test_frozen_server.py <path-to-frozen-exe> [--fixture <offer.html>]
  python lab/test_frozen_server.py --python-server [--fixture <offer.html>]

  --python-server runs the SAME tiers against `python server/server.py` (the
  non-frozen dev server) -- the discriminating half of the pair: it isolates a
  Windows stdin/handle interaction (reproduces on the dev server too) from a
  frozen-bootloader one (frozen exe only).

  CANDIDATE_SUITE_DIR (env)        required for T3/T4; T0-T2 run without it.
  AGENT_CANDIDATE_OUTPUT_DIR (env) where T3 writes the .md; defaults to a tempdir.

EXIT CODES
  0  all attempted tiers passed (or cleanly SKIPPED: no binary path given)
  1  a tier FAILED an assertion, or the server raised
  2  a step TIMED OUT (suspected frozen stdio / event-loop hang)
  3  usage error (binary path given but missing)
"""

import asyncio
import json
import os
import sys
import tempfile
import traceback
from datetime import timedelta
from pathlib import Path

# Resolve the single-source contract from the ship-side core (lab depends on
# server, never the reverse). Importing chain_core does NOT require
# CANDIDATE_SUITE_DIR (it is read lazily, only when a suite script is invoked).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
import chain_core as core  # noqa: E402

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

STEP_TIMEOUT = 30.0  # seconds; a frozen stdio hang must fail, not wait forever

EXPECTED_TOOLS = {core.LOAD_POSTING_NAME, core.BRIEF_NAME, core.LETTER_NAME}

# The .mcpb manifest advertises the same tool contract to the host. It is a
# hand-maintained file, so T1 asserts it against the live tools/list to keep it a
# verified projection of the single source -- not a fourth copy free to drift
# (a manifest/runtime mismatch makes the host refuse the server in default mode).
MANIFEST_TOOLS = {
    t["name"]
    for t in json.loads(
        (Path(__file__).resolve().parent.parent / "manifest.json").read_text(
            encoding="utf-8"
        )
    )["tools"]
}

# Product version the server advertises at the initialize handshake
# (serverInfo.version). Bound to the SAME manifest so a bump in one place
# without the other fails T0 -- the version analogue of the tools parity above.
MANIFEST_VERSION = json.loads(
    (Path(__file__).resolve().parent.parent / "manifest.json").read_text(
        encoding="utf-8"
    )
)["version"]


class Fail(Exception):
    """A tier assertion failed -> exit 1."""


def _check(cond, msg):
    if not cond:
        raise Fail(msg)


def _emit(tier, status, detail):
    """Print a tier result the moment it is known (incremental reporting)."""
    print("  [%-4s] %s  %s" % (status, tier, detail))


def _text_of(result):
    """Concatenate the text of all TextContent blocks in a CallToolResult."""
    out = []
    for block in result.content or []:
        t = getattr(block, "text", None)
        if t is not None:
            out.append(t)
    return "\n".join(out)


def _leaves(exc):
    """Flatten a (possibly nested) ExceptionGroup to its leaf exceptions."""
    if isinstance(exc, BaseExceptionGroup):
        out = []
        for sub in exc.exceptions:
            out.extend(_leaves(sub))
        return out
    return [exc]


def _brief_payload():
    """A minimal VALID generate_posting_brief argument set, fictional values.

    Label keys are single-sourced from chain_core (the real script refuses any
    divergence from this exact key set, exit 1); only the values are local.
    """
    return {
        "company_name": "Helvetia Robotics SA",
        "job_title": "Staff Platform Engineer",
        "posting_language": "en",
        "requirements": ["Kubernetes", "observability", "platform reliability"],
        "posting_body": "We are hiring a Staff Platform Engineer for our team.",
        "labels": {k: k.replace("_", " ").title() for k in core.BRIEF_LABEL_KEYS},
        "language": "en",
    }


async def _run_tiers(command, server_args, fixture, suite_dir, out_dir, errlog):
    env = {**os.environ}
    if suite_dir:
        env["CANDIDATE_SUITE_DIR"] = suite_dir
    env["AGENT_CANDIDATE_OUTPUT_DIR"] = str(out_dir)
    # Frozen mode : command=<exe>, server_args=[] (no --run -> server path; the
    # binary is UTF-8 by design, -X utf8 baked in).
    # Dev discriminator (--python-server) : command=<python>, server_args=
    # [server/server.py] -- the SAME tiers against the NON-frozen server. Same
    # inherited fds, different child (python vs frozen exe), so a Windows-stdin
    # interaction reproduces here while a frozen-bootloader one does not.
    params = StdioServerParameters(
        command=str(command), args=list(server_args), env=env
    )

    # errlog captures the SERVER's stderr -- a frozen boot crash lands here.
    async with stdio_client(params, errlog=errlog) as (read, write):
        async with ClientSession(read, write) as session:
            # T0 -- boot + handshake. Where a frozen server hangs or dies.
            init = await asyncio.wait_for(session.initialize(), STEP_TIMEOUT)
            _check(
                init.serverInfo.name == core.SERVER_NAME,
                "serverInfo.name %r != %r" % (init.serverInfo.name, core.SERVER_NAME),
            )
            _check(
                init.serverInfo.version == MANIFEST_VERSION,
                "serverInfo.version %r != manifest %r (version wiring missing or "
                "half-bumped: Server(version=core.SERVER_VERSION) and manifest.json "
                "must move together)"
                % (init.serverInfo.version, MANIFEST_VERSION),
            )
            _check(bool(init.protocolVersion), "empty protocolVersion")
            _emit(
                "T0",
                "PASS",
                "server=%s proto=%s" % (init.serverInfo.name, init.protocolVersion),
            )

            # T1 -- capability advertisement; the single source must survive the
            # JSON-RPC seam AND match what the .mcpb manifest advertises to the host.
            listed = await asyncio.wait_for(session.list_tools(), STEP_TIMEOUT)
            names = {tool.name for tool in listed.tools}
            _check(
                names == EXPECTED_TOOLS,
                "tools/list %s != expected %s"
                % (sorted(names), sorted(EXPECTED_TOOLS)),
            )
            _check(
                names == MANIFEST_TOOLS,
                "tools/list %s != manifest %s (manifest drifted from the runtime "
                "contract; host would refuse default mode)"
                % (sorted(names), sorted(MANIFEST_TOOLS)),
            )
            _emit("T1", "PASS", "tools=%s == manifest" % sorted(names))

            # T2 -- in-process tool. Proves call dispatch on the frozen binary AND
            # that the ingestion sanitiser RUNS inside the frozen server.
            if fixture is None:
                _emit("T2", "SKIP", "no fixture (pass --fixture <offer.html>)")
            else:
                r = await session.call_tool(
                    core.LOAD_POSTING_NAME,
                    {"offer_path": str(fixture)},
                    read_timeout_seconds=timedelta(seconds=STEP_TIMEOUT),
                )
                _check(
                    not r.isError, "load_job_posting returned isError: " + _text_of(r)
                )
                body = _text_of(r)
                _check(
                    body.startswith(core.POSTING_RESULT_PREFIX),
                    "missing POSTING_RESULT_PREFIX",
                )
                low = body.lower()
                _check("<!--" not in body, "HTML comment survived the sanitiser")
                _check("<script" not in low, "<script> survived the sanitiser")
                _check("<style" not in low, "<style> survived the sanitiser")
                _emit("T2", "PASS", "%d chars, no non-rendered carrier" % len(body))

            # T3 -- the real deployment path: JSON-RPC call -> server handler ->
            # subprocess spawn of THIS SAME frozen exe with --run brief
            # (self-re-exec) -> candidate-suite writes a .md -> path back over the
            # wire. The highest-risk frozen seam. Needs CANDIDATE_SUITE_DIR.
            if not suite_dir:
                _emit("T3", "SKIP", "CANDIDATE_SUITE_DIR unset")
                _emit("T4", "SKIP", "CANDIDATE_SUITE_DIR unset")
                return

            r = await session.call_tool(
                core.BRIEF_NAME,
                _brief_payload(),
                read_timeout_seconds=timedelta(seconds=STEP_TIMEOUT),
            )
            _check(
                not r.isError, "generate_posting_brief returned isError: " + _text_of(r)
            )
            txt = _text_of(r)
            _check(
                txt.startswith(core.BRIEF_RESULT_PREFIX), "missing BRIEF_RESULT_PREFIX"
            )
            md_path = txt[len(core.BRIEF_RESULT_PREFIX) :].strip()
            _check(
                md_path.endswith(".md") and Path(md_path).exists(),
                "announced .md path does not exist: " + md_path,
            )
            _emit("T3", "PASS", "self-re-exec wrote " + Path(md_path).name)

            # T4 -- the refusal contract survives the JSON-RPC seam: a blank
            # critical field must come back as isError (exit 2 in the child).
            bad = _brief_payload()
            bad["company_name"] = ""
            r = await session.call_tool(
                core.BRIEF_NAME,
                bad,
                read_timeout_seconds=timedelta(seconds=STEP_TIMEOUT),
            )
            _check(
                bool(r.isError),
                "blank critical field did NOT raise isError (contract broken)",
            )
            _emit("T4", "PASS", "blank field -> isError (contract held)")


def main(argv):
    if len(argv) < 1:
        print("SKIPPED: no target given (build the win-x64 exe first).")
        print(
            "  usage: python lab/test_frozen_server.py <exe> [--fixture <offer.html>]"
        )
        print(
            "         python lab/test_frozen_server.py --python-server [--fixture <offer.html>]"
        )
        return 0

    server_py = Path(__file__).resolve().parent.parent / "server" / "server.py"
    if argv[0] == "--python-server":
        # Discriminator: same tiers against the non-frozen dev server.
        command = sys.executable
        server_args = [str(server_py)]
        target_label = "DEV server (%s %s)" % (Path(sys.executable).name, server_py)
    else:
        exe = Path(argv[0]).expanduser()
        if not exe.exists():
            print("USAGE ERROR: binary not found: %s" % exe)
            return 3
        command = str(exe)
        server_args = []
        target_label = "FROZEN binary (%s)" % exe

    fixture = None
    if "--fixture" in argv:
        fixture = Path(argv[argv.index("--fixture") + 1]).expanduser().resolve()
        if not fixture.exists():
            print("USAGE ERROR: fixture not found: %s" % fixture)
            return 3
    else:
        default_fx = (
            Path(__file__).resolve().parent / "fixtures" / "offer_atlas_banque.html"
        )
        if default_fx.exists():
            fixture = default_fx

    suite_dir = os.environ.get("CANDIDATE_SUITE_DIR", "").strip() or None
    out_dir = Path(
        os.environ.get("AGENT_CANDIDATE_OUTPUT_DIR")
        or tempfile.mkdtemp(prefix="frozen_server_smoke_")
    )

    print("Frozen MCP-server smoke test")
    print("  target  : %s" % target_label)
    print("  fixture : %s" % (fixture or "(none -> T2 skipped)"))
    print("  suite   : %s" % (suite_dir or "(unset -> T3/T4 skipped)"))
    print("  output  : %s" % out_dir)
    print("-" * 60)

    # Capture the server's stderr to a file so a frozen boot crash is recoverable.
    err_fd, err_path = tempfile.mkstemp(prefix="frozen_server_stderr_", suffix=".log")
    err_handle = os.fdopen(err_fd, "w", encoding="utf-8", errors="replace")

    raised = None
    try:
        asyncio.run(
            _run_tiers(command, server_args, fixture, suite_dir, out_dir, err_handle)
        )
    except BaseException as e:  # noqa: BLE001 -- re-classified and reported below
        raised = e
    finally:
        err_handle.flush()
        err_handle.close()

    server_err = Path(err_path).read_text(encoding="utf-8", errors="replace").strip()
    try:
        os.unlink(err_path)
    except OSError:
        pass

    print("-" * 60)
    if raised is None:
        print("RESULT: PASS")
        return 0

    leaves = _leaves(raised)
    timed_out = any(isinstance(x, (asyncio.TimeoutError, TimeoutError)) for x in leaves)
    only_fail = bool(leaves) and all(isinstance(x, Fail) for x in leaves)

    if only_fail:
        for x in leaves:
            print("[FAIL] %s" % x)
    else:
        for x in leaves:
            print("[ERROR] %s: %s" % (type(x).__name__, x))
            tb = "".join(
                traceback.format_exception(type(x), x, x.__traceback__)
            ).rstrip()
            print(tb)

    if server_err:
        print(("--- frozen server stderr ").ljust(60, "-"))
        print(server_err)
        print("-" * 60)
    else:
        print("(frozen server wrote nothing to stderr)")

    if timed_out:
        print("RESULT: TIMEOUT (suspected frozen stdio / event-loop hang)")
        return 2
    print("RESULT: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
