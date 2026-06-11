#!/usr/bin/env python3
"""test_frozen_build.py -- install-proof for the frozen (win-x64) binary.

NOT part of the 132-check floor: the floor must pass with NO build product, so
this proof lives apart and runs ONLY when the PyInstaller onedir build exists.
It is the artifact that promotes the self-re-exec RESIDUAL: the [8] floor MOCKS
`sys.frozen`; here the REAL frozen binary runs candidate-suite end to end. No
model, no API -- it only drives the local binary, so it is a deterministic
EXECUTION proof, not a paid run.

What it proves, against the REAL binary (not a mock):
  [F1] dispatch guard fires in the frozen binary  -> `--run <unknown>` exits 1
  [F2] brief path: library closure + success       -> `--run brief ...`  exits 0, .md  produced
  [F3] letter path: python-docx / lxml closure      -> `--run letter ...` exits 0, .docx produced
  [F4] refusal contract survives freezing           -> blank critical field exits 2

Single source: field NAMES and the candidate profile are imported from
chain_core; only sample VALUES live here (fixtures, not contract logic). The CLI
arg SHAPE targets candidate-suite's own pinned CLI (SHA 2863162).

Run (repo root, venv, after building):
    CANDIDATE_SUITE_DIR=../candidate-suite python lab/test_frozen_build.py
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Resolve candidate-suite BEFORE importing chain_core: the core reads
# CANDIDATE_SUITE_DIR at import time, and we reuse it to resolve the template.
SUITE = os.environ.get("CANDIDATE_SUITE_DIR") or str(REPO.parent / "candidate-suite")
os.environ["CANDIDATE_SUITE_DIR"] = SUITE

sys.path.insert(0, str(REPO / "server"))
import chain_core as core  # noqa: E402  (path insert must precede the import)

# Locate the onedir binary (.exe on Windows). Absent -> SKIP, not a pass.
_EXE = (
    REPO
    / "dist"
    / "agent-candidate"
    / ("agent-candidate.exe" if os.name == "nt" else "agent-candidate")
)
if not _EXE.exists():
    print("SKIP: no build at", _EXE)
    print("      run `pyinstaller packaging/agent-candidate.spec` first.")
    sys.exit(2)

# Child env mirrors chain_core's: UTF-8 so the scripts' emoji prints cannot
# crash a cp1252 console; MSYS_NO_PATHCONV so Git Bash does not mangle the IANA
# zone. (Args are passed as a list with shell=False, so the shell never sees
# them, but we keep parity with the shipped wrapper.)
_ENV = {
    **os.environ,
    "CANDIDATE_SUITE_DIR": SUITE,
    "PYTHONUTF8": "1",
    "PYTHONIOENCODING": "utf-8",
    "MSYS_NO_PATHCONV": "1",
}

_FAILURES = []


def _run(args):
    return subprocess.run(
        [str(_EXE), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_ENV,
    )


def _check(label, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + label + (("  -- " + detail) if detail else ""))
    if not ok:
        _FAILURES.append(label)


# --- Fixtures, built from chain_core's single-source field lists -------------
def _brief_argv(out_dir, data_overrides=None):
    data = {f: "sample " + f for f in core.BRIEF_MODEL_FIELDS}
    data["posting_language"] = "en"
    data["requirements"] = ["First requirement", "Second requirement"]
    if data_overrides:
        data.update(data_overrides)
    labels = {k: "L_" + k for k in core.BRIEF_LABEL_KEYS}
    return [
        "--run",
        "brief",
        "--language",
        "en",
        "--output-dir",
        str(out_dir),
        "--timezone",
        core.CANDIDATE_TIMEZONE,
        "--data-json",
        json.dumps(data, ensure_ascii=False),
        "--labels-json",
        json.dumps(labels, ensure_ascii=False),
    ]


def _letter_argv(out_path, template, data_overrides=None):
    data = {f: "Sample " + f + "." for f in core.LETTER_MODEL_FIELDS}
    data["company_name"] = "Helvetia Robotics"
    data["job_title"] = "Staff Platform Engineer"
    data["date_line"] = "Paris, le 11 juin 2026"
    data["closing"] = "Yours sincerely,"  # no name -> the template signs
    if data_overrides:
        data.update(data_overrides)
    data.update(core.CANDIDATE_PROFILE)  # trusted sender_* fields
    return [
        "--run",
        "letter",
        "--language",
        "en",
        "--template-path",
        str(template),
        "--output-path",
        str(out_path),
        "--data-json",
        json.dumps(data, ensure_ascii=False),
    ]


def main():
    print("Frozen-binary install-proof:", _EXE)
    print("candidate-suite:", SUITE)
    print("-" * 60)
    template = core.resolve_suite_paths()["template"]

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # [F1] dispatch guard fires in the REAL frozen binary.
        r = _run(["--run", "no_such_kind"])
        _check(
            "[F1] unknown --run kind -> exit 1",
            r.returncode == 1,
            "got exit " + str(r.returncode),
        )

        # [F2] brief path: candidate-suite runs through the frozen interpreter,
        # its imports resolve, a .md is produced.
        before = set(tmp.glob("*.md"))
        r = _run(_brief_argv(tmp))
        md = sorted(set(tmp.glob("*.md")) - before)
        _check(
            "[F2] brief -> exit 0 + .md produced",
            r.returncode == 0 and bool(md),
            "exit "
            + str(r.returncode)
            + "; "
            + (r.stderr.strip()[-300:] if r.returncode else ""),
        )

        # [F3] letter path: this is the one that exercises python-docx / lxml
        # INSIDE the frozen binary -- the real library-closure test.
        letter_path = tmp / "letter.docx"
        r = _run(_letter_argv(letter_path, template))
        _check(
            "[F3] letter -> exit 0 + .docx produced",
            r.returncode == 0 and letter_path.exists(),
            "exit "
            + str(r.returncode)
            + "; "
            + (r.stderr.strip()[-300:] if r.returncode else ""),
        )

        # [F4] refusal contract survives freezing: a blanked critical field must
        # make the REAL child sys.exit(2), and that code must propagate out.
        r = _run(_letter_argv(tmp / "refused.docx", template, {"company_name": ""}))
        _check(
            "[F4] blank critical field -> exit 2 (refusal propagated)",
            r.returncode == 2,
            "got exit " + str(r.returncode),
        )

    print("-" * 60)
    if _FAILURES:
        print("FROZEN PROOF FAILED:", ", ".join(_FAILURES))
        return 1
    print(
        "FROZEN PROOF GREEN: the real binary runs candidate-suite and keeps the contract."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
