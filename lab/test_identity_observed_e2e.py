"""Observed (end-to-end) floor for family c1 -- the "biting" half of the DoD.

The structural floor (test_identity_binding_floor.py) proves the channel is
removed and candidate_name is injected at payload-composition time. This test
goes one step further: it RENDERS each of the five deliverables through the real
candidate-suite generators and asserts the rendered artifact carries the
fictional identity ``Robin Mercier`` and NOT the identity present in the input.

It feeds candidate-suite's own complete sample payloads (which carry the sample
identity ``Jordan Lee-Carter``) through the agent-candidate wrappers. Because the
wrapper injects from CANDIDATE_PROFILE and the profile wins, the rendered output
must show ``Robin Mercier`` -- a strictly stronger check than "target fields
only": even a caller-supplied identity is overridden end-to-end.

Requires candidate-suite checked out and CANDIDATE_SUITE_DIR set (as in the Floor
CI gate). When the suite is absent (unit-only runs) the tests skip cleanly.
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
import chain_core as core  # noqa: E402

SAMPLE_NAME = "Jordan Lee-Carter"  # the identity present in the suite's sample input
FICTIONAL = "Robin Mercier"  # what the wrapper must force into every output

# candidate-suite _GENERATORS keys -> agent-candidate build_* function names.
MD_MAP = {
    "strategic_playbook": ("05_strategic_playbook", "build_playbook"),
    "application_summary": ("03_application_summary", "build_summary"),
    "interview_prep": ("04_interview_prep", "build_interview"),
    "quick_reference": ("06_quick_reference", "build_refcard"),
}


class _SuiteUnavailable(RuntimeError):
    pass


def _load_build_samples():
    """Import candidate-suite's build_samples (the complete fictional fixtures).
    Returns the module, or None if the suite is not checked out."""
    suite = os.environ.get("CANDIDATE_SUITE_DIR")
    if not suite:
        return None
    tooling = Path(suite) / "tooling"
    if not (tooling / "build_samples.py").exists():
        return None
    sys.path.insert(0, str(tooling))
    try:
        import build_samples

        return build_samples
    except Exception:
        return None


def _require_samples():
    bs = _load_build_samples()
    if bs is None:
        try:
            import pytest

            pytest.skip("CANDIDATE_SUITE_DIR / build_samples not available")
        except ImportError:
            raise _SuiteUnavailable(
                "SKIP: CANDIDATE_SUITE_DIR / build_samples not available"
            )
    return bs


def test_md_generators_render_fictional_identity():
    """The four corrected generators render Robin Mercier; the input identity
    does not survive into the output."""
    bs = _require_samples()
    failures = []
    with tempfile.TemporaryDirectory() as td:
        for tool, (key, fn_name) in MD_MAP.items():
            sample = bs._GENERATORS[key]
            data = dict(sample["data"], labels=sample["labels"], language="en")
            out = getattr(core, fn_name)(data, output_dir=td)
            text = Path(out).read_text(encoding="utf-8")
            if FICTIONAL not in text:
                failures.append(f"{tool}: rendered output missing {FICTIONAL!r}")
            if SAMPLE_NAME in text:
                failures.append(
                    f"{tool}: caller-supplied {SAMPLE_NAME!r} leaked into output"
                )
    assert not failures, "identity not forced in rendered output:\n  " + "\n  ".join(
        failures
    )


def test_cover_letter_renders_fictional_identity():
    """The already-bound letter renders Robin Mercier as the signatory; the
    caller-supplied sender identity does not survive."""
    bs = _require_samples()
    from docx import Document

    data = dict(bs.lorem_letter_data(signed=False), language="en")
    with tempfile.TemporaryDirectory() as td:
        out = core.build_letter(data, output_dir=td)
        text = "\n".join(p.text for p in Document(out).paragraphs)
    assert FICTIONAL in text, f"cover_letter missing {FICTIONAL!r}"
    assert SAMPLE_NAME not in text, (
        f"caller-supplied {SAMPLE_NAME!r} leaked into cover_letter"
    )


if __name__ == "__main__":
    _tests = [
        test_md_generators_render_fictional_identity,
        test_cover_letter_renders_fictional_identity,
    ]
    red = 0
    skipped = 0
    for _t in _tests:
        try:
            _t()
            print(f"[PASS] {_t.__name__}")
        except _SuiteUnavailable as exc:
            skipped += 1
            print(f"[SKIP] {_t.__name__}: {exc}")
        except AssertionError as exc:
            red += 1
            print(
                f"[FAIL] {_t.__name__}\n        " + str(exc).replace("\n", "\n        ")
            )
    print(f"\n{red} failure(s), {skipped} skipped / {len(_tests)} observed e2e checks")
    sys.exit(1 if red else 0)
