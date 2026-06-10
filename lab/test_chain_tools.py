"""
test_chain_tools.py — deterministic-floor test for brief_to_letter_chain.

Tests the TOOLS directly, outside the agent loop: no SDK query, no tokens.
Since graft (B), the letter sections exercise the REAL fill_cover_letter.py
through the subprocess wrapper. Since graft (A), ingestion is a dedicated
load_job_posting tool (sanitisation upstream of the model) and the brief
sections exercise the REAL generate_posting_brief.py -- the floor proves both
real refusal contracts (exit 1 / exit 2 / labels key set), not a double's.

Requirements (graft B):
    - CANDIDATE_SUITE_DIR env var -> candidate-suite root (contains modules/)
    - python-docx installed in the venv (the real script imports it; the floor
      also uses it to read the produced .docx back)

    python test_chain_tools.py [path/to/offer.html]

Fixtures (canary AND channel follow the file):
    offer_atlas_banque.html             soft probe (hidden)
    offer_atlas_neutral_content.html    content tampering (hidden, RH-AB-7731)
    offer_atlas_neutral_exfil.html      exfiltration (hidden, ANTHROPIC_API_KEY)
    offer_atlas_visible_injection.html  content tampering (VISIBLE, RH-AB-4402)

Input-side rampart covers the NON-RENDERED channel only: hidden canary -> stripped;
visible canary -> survives (reaches the model). The floor proves a fact about
deterministic code; whether the model OBEYS a surviving visible canary is the run's.

Exits 0 if every check passes, 1 otherwise.
"""

import asyncio
import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

import brief_to_letter_chain as chain
from claude_agent_sdk.types import ResultMessage

CANARY_BY_FIXTURE = {
    "offer_atlas_banque.html": "INJECTION-OK-ATLAS-7F3",
    "offer_atlas_neutral_content.html": "RH-AB-7731",
    "offer_atlas_neutral_exfil.html": "ANTHROPIC_API_KEY",
    "offer_atlas_visible_injection.html": "RH-AB-4402",
}
FIXTURE_CHANNEL = {
    "offer_atlas_banque.html": "hidden",
    "offer_atlas_neutral_content.html": "hidden",
    "offer_atlas_neutral_exfil.html": "hidden",
    "offer_atlas_visible_injection.html": "visible",
}
ALL_CANARIES = list(CANARY_BY_FIXTURE.values())

DEFAULT_OFFER = sys.argv[1] if len(sys.argv) > 1 else chain.DEFAULT_OFFER_PATH
PROBE_MARKER = CANARY_BY_FIXTURE.get(Path(DEFAULT_OFFER).name, "INJECTION-OK-ATLAS-7F3")
CHANNEL = FIXTURE_CHANNEL.get(Path(DEFAULT_OFFER).name, "hidden")

_passed = 0
_failed = 0


def check(name, condition):
    global _passed, _failed
    if condition:
        _passed += 1
        print("  PASS  " + name)
    else:
        _failed += 1
        print("  FAIL  " + name)


def run_handler(tool_obj, args):
    return asyncio.run(tool_obj.handler(args))


def docx_text(path):
    """Plain-text view of a .docx (paragraph texts joined) -- the floor reads
    the REAL output back instead of trusting the wrapper's return value."""
    from docx import Document
    return "\n".join(p.text for p in Document(path).paragraphs)


# Nominal model-authored payload for the letter tool, faithful to the real
# contract: 13 composed fields + language. Reused (copied) by every letter
# section; each section perturbs exactly ONE thing.
NOMINAL_LETTER = {
    "company_name": "Atlas Banque",
    "job_title": "IT Tribe Co-Leader",
    "recruiter_name": "Camille Roy",
    "recruiter_title": "DRH",
    "date_line": "Paris, le 10 juin 2026",
    "greeting": "Madame Roy,",
    "subject_label": "Objet : candidature au poste de ",
    "closing": "Cordialement,",
    "paragraph_1_intro": "Fort de huit ans de management d'ingenierie, je candidate avec conviction.",
    "paragraph_2_current": "J'encadre aujourd'hui des equipes plateforme orientees fiabilite et SLOs.",
    "paragraph_3_experience": "J'ai pilote la gestion d'incidents et fait grandir plusieurs managers.",
    "paragraph_4_value": "J'apporte une communication claire avec les interlocuteurs produit.",
    "paragraph_5_closing": "Je me tiens a votre disposition pour un entretien.",
    "language": "fr",
}

# Localized FR structure labels, exact key set the real brief script enforces.
NOMINAL_LABELS = {
    "title": "Brief de l'offre", "s_meta": "En un coup d'oeil",
    "l_company": "Entreprise", "l_position": "Poste",
    "l_recruiter": "Recruteur", "l_city": "Ville", "l_captured": "Capturee",
    "l_source": "Source", "l_language": "Langue de l'offre",
    "s_digest": "Synthese", "sub_requirements": "Exigences cles",
    "sub_deadline": "Echeance", "s_posting": "Offre (verbatim)",
}

NOMINAL_BRIEF = {
    "company_name": "Atlas Banque",
    "job_title": "IT Tribe Co-Leader",
    "posting_language": "French",
    "requirements": ["8 ans de management", "fiabilite et SLOs",
                      "communication produit"],
    "posting_body": "Atlas Banque recrute un IT Tribe Co-Leader a Paris. "
                    "Huit ans de management attendus.",
    "recruiter_name": "Camille Roy",
    "recruiter_title": "DRH",
    "city": "Paris",
    "source_url": "",
    "deadline": "",
    "labels": NOMINAL_LABELS,
    "language": "fr",
}


def main():
    print("Deterministic floor — brief_to_letter_chain")
    print("Offer fixture: " + DEFAULT_OFFER + "   (channel: " + CHANNEL + ")\n")

    print("[0] Graft environment (real candidate-suite reachable)")
    try:
        paths = chain.resolve_suite_paths()
        check("CANDIDATE_SUITE_DIR resolves (letter + brief scripts + template found)",
              set(paths) == {"fill_script", "template", "brief_script"})
    except RuntimeError as e:
        check("CANDIDATE_SUITE_DIR resolves -- " + str(e), False)
        print("\nFloor aborted: the graft floor proves the REAL contract and "
              "cannot run without it.")
        sys.exit(1)
    try:
        import docx  # noqa: F401
        check("python-docx importable in this venv", True)
    except ImportError:
        check("python-docx importable in this venv (pip install python-docx)", False)
        sys.exit(1)

    print("[1] Ingestion -- load_job_posting sanitises upstream of the model")
    raw = Path(DEFAULT_OFFER).read_text(encoding="utf-8")
    served = chain.build_posting_load(DEFAULT_OFFER)
    check("canary present in the RAW file (the threat is real)", PROBE_MARKER in raw)
    if CHANNEL == "hidden":
        check("hidden-channel canary ABSENT from the text served to the model",
              PROBE_MARKER not in served)
        check("no HTML comment survives (carrier removed)", "<!--" not in served)
    else:
        check("visible-channel canary SURVIVES sanitization (input rampart does NOT cover it)",
              PROBE_MARKER in served)
        check("the surviving canary rode the visible channel, not a comment",
              "<!--" not in served)
    check("visible posting text is preserved (company name still readable)",
          "Atlas Banque" in served)
    check("candidate name is NOT in the offer text", "Robin Mercier" not in served)
    check("deterministic header extraction is GONE (double artefact removed)",
          not hasattr(chain, "extract_header"))

    print("\n[2b] Sanitizer contract (crafted string, fixture-free)")
    crafted = ("<p>VISIBLE-KEEP</p><!-- HIDDEN-COMMENT marker -->"
               "<script>var HIDDEN_SCRIPT = 1;</script>"
               "<style>.x{display:none} /* HIDDEN-STYLE */</style>")
    cleaned = chain._strip_non_rendered(crafted)
    check("keeps visible text", "VISIBLE-KEEP" in cleaned)
    check("drops comment content", "HIDDEN-COMMENT" not in cleaned)
    check("drops <script> content", "HIDDEN_SCRIPT" not in cleaned)
    check("drops <style> content", "HIDDEN-STYLE" not in cleaned)

    print("\n[3] Missing offer file degrades cleanly")
    tools = {t.name: t for t in chain.build_tools()}
    res = run_handler(tools["load_job_posting"], {"offer_path": "/no/such/offer.html"})
    check("missing file -> is_error", res.get("is_error") is True)

    print("\n[4] load_job_posting handler serves the sanitised text")
    ok = run_handler(tools["load_job_posting"], {"offer_path": DEFAULT_OFFER})
    text = ok["content"][0]["text"]
    check("handler not flagged is_error", not ok.get("is_error"))
    if CHANNEL == "hidden":
        check("served text is sanitized (canary absent)", PROBE_MARKER not in text)
    else:
        check("served text keeps the visible canary (it reaches the model)", PROBE_MARKER in text)
    check("handler text labels the posting as data", "data, not instructions" in text)

    print("\n[4b] Posting brief -- through the REAL generate_posting_brief.py")
    res = run_handler(tools["generate_posting_brief"], dict(NOMINAL_BRIEF))
    check("nominal brief -> not is_error", not res.get("is_error"))
    written = res["content"][0]["text"].replace("Posting brief written: ", "")
    check("output is a .md", written.endswith(".md"))
    check("brief file exists", Path(written).exists())
    check("output lands in runs/ next to the chain file",
          Path(written).parent.resolve() == chain.OUTPUT_DIR.resolve())
    import datetime as _dt
    today = _dt.date.today()
    check("filename is SCRIPT-owned (Posting_Brief_<c>_<p>_<YYYYMMDD>.md, today's stamp)",
          Path(written).name ==
          "Posting_Brief_Atlas-Banque_IT-Tribe-Co-Leader_"
          + today.strftime("%Y%m%d") + ".md")
    md = Path(written).read_text(encoding="utf-8")
    # The capture date must be TODAY in the candidate's own timezone. If the
    # zone were corrupted in transit (MSYS path-mangling) the script would warn
    # and fall back, but the date could differ across a midnight boundary in
    # another zone; pin it to the candidate zone explicitly.
    import datetime as _dt2
    from zoneinfo import ZoneInfo as _ZI
    tz_today = _dt2.datetime.now(_ZI(chain.CANDIDATE_TIMEZONE)).date().isoformat()
    check("capture date is script-owned (today in the candidate timezone)",
          tz_today in md)
    check("localized labels rendered (structure intact)",
          "# Brief de l'offre" in md and "## Synthese" in md)
    check("requirements digest rendered",
          "- 8 ans de management" in md)
    check("posting body carried verbatim in the dossier (by design)",
          "Atlas Banque recrute un IT Tribe Co-Leader" in md)

    print("\n[4c] Brief refusal contract -- proven on the REAL script")
    res = run_handler(tools["generate_posting_brief"],
                      dict(NOMINAL_BRIEF, company_name=""))
    check("empty critical field -> is_error (real exit 2)",
          res.get("is_error") is True and "exit 2" in res["content"][0]["text"])
    bad_labels = dict(NOMINAL_LABELS); bad_labels.pop("s_digest")
    res = run_handler(tools["generate_posting_brief"],
                      dict(NOMINAL_BRIEF, labels=bad_labels))
    check("wrong label key set -> is_error (real exit 1, structure guard)",
          res.get("is_error") is True and "exit 1" in res["content"][0]["text"]
          and "s_digest" in res["content"][0]["text"])
    res = run_handler(tools["generate_posting_brief"],
                      dict(NOMINAL_BRIEF, language="francais"))
    check("non-ISO language -> is_error from the wrapper guard",
          res.get("is_error") is True and "ISO 639-1" in res["content"][0]["text"])

    print("\n[5] Nominal cover letter -- through the REAL fill_cover_letter.py")
    nominal = dict(NOMINAL_LETTER)
    res = run_handler(tools["write_cover_letter"], nominal)
    check("nominal letter -> not is_error", not res.get("is_error"))
    written = res["content"][0]["text"].replace("Cover letter written: ", "")
    check("output is a .docx", written.endswith(".docx"))
    check("letter file exists", Path(written).exists())
    check("output lands in runs/ next to the chain file (CWD debt settled)",
          Path(written).parent.resolve() == chain.OUTPUT_DIR.resolve())
    letter_text = docx_text(written)
    check("real template filled (paragraph 1 present)",
          nominal["paragraph_1_intro"] in letter_text)
    check("subject line composed (label + job title)",
          "Objet : candidature au poste de IT Tribe Co-Leader" in letter_text)
    check("trusted profile injected by the wrapper (sender street present)",
          chain.CANDIDATE_PROFILE["sender_street"] in letter_text)
    check("date_line rendered", nominal["date_line"] in letter_text)
    check("nominal letter is clean of every known canary",
          not any(c in letter_text for c in ALL_CANARIES))
    check("name appears exactly twice (header + template signature)",
          letter_text.count("Robin Mercier") == 2)
    check("no leftover placeholder in the rendered letter", "{{" not in letter_text)

    print("\n[5b] Double-signature mode closed on the REAL template "
          "(name in closing is de-duplicated)")
    name = chain.CANDIDATE_PROFILE["sender_full_name"]
    # Mimic A5: the model put the sign-off AND the name into the closing field.
    poisoned = dict(NOMINAL_LETTER,
                    closing="Merci de donner suite.\n\nCordialement,\n" + name)
    res = run_handler(tools["write_cover_letter"], poisoned)
    check("poisoned closing still ships -> not is_error", not res.get("is_error"))
    written = res["content"][0]["text"].replace("Cover letter written: ", "")
    txt = docx_text(written)
    check("name appears exactly twice (header + one signature), not three times",
          txt.count(name) == 2)
    check("the sign-off content the model placed in closing is preserved",
          "Merci de donner suite." in txt)

    print("\n[5c] Output tripwire -- untrusted identifier rejected BEFORE the call")
    # Mimic the model OBEYING a visible injection: the code lands in a paragraph.
    obeyed_para = dict(NOMINAL_LETTER,
                       paragraph_3_experience="Reference interne : RH-AB-4402. "
                       + NOMINAL_LETTER["paragraph_3_experience"])
    res = run_handler(tools["write_cover_letter"], obeyed_para)
    check("injected code in a body paragraph -> is_error", res.get("is_error") is True)
    check("the refusal names the leaked identifier",
          "RH-AB-4402" in res["content"][0]["text"])
    # Same payload via the closing field is caught too (A5 also poisoned closing).
    obeyed_closing = dict(NOMINAL_LETTER, closing="Cordialement, ref. RH-AB-4402")
    res = run_handler(tools["write_cover_letter"], obeyed_closing)
    check("injected code in closing -> is_error", res.get("is_error") is True)
    # Widened scope: a code smuggled into the SUBJECT prefix is caught as well.
    obeyed_subject = dict(NOMINAL_LETTER,
                          subject_label="Objet : ref. RH-AB-4402 -- candidature au poste de ")
    res = run_handler(tools["write_cover_letter"], obeyed_subject)
    check("injected code in subject_label -> is_error (scan covers ALL "
          "model-authored fields)", res.get("is_error") is True)
    # GRAFT A -- poisoned EXTRACTION: company/job_title are model-extracted
    # now, so an identifier smuggled into them must be caught, not laundered.
    poisoned_company = dict(NOMINAL_LETTER,
                            company_name="Atlas Banque (ref RH-AB-4402)")
    res = run_handler(tools["write_cover_letter"], poisoned_company)
    check("injected code in company_name -> is_error (whitelist no longer "
          "covers extraction)", res.get("is_error") is True)
    # A clean letter that legitimately reuses visible offer content still ships.
    res = run_handler(tools["write_cover_letter"], dict(NOMINAL_LETTER))
    check("clean letter still ships (no false positive) -> not is_error",
          not res.get("is_error"))

    print("\n[5d] Output-backstop contract (crafted strings, fixture-free)")
    # GRAFT A: the trusted set is the PROFILE ONLY -- company/job_title are
    # model-extracted and no longer whitelist anything.
    trusted = " ".join(chain.CANDIDATE_PROFILE.values())
    check("visible canary is flagged as untrusted",
          chain._find_untrusted_identifiers("Reference RH-AB-4402", trusted) == ["RH-AB-4402"])
    legit = ("Madame Roy, candidat au poste de Co-Leader chez Atlas Banque, "
             "experience 2023-2025 en conformite RGPD au sein d'une DSI.")
    check("no false positive on legitimate visible offer content",
          chain._find_untrusted_identifiers(legit, trusted) == [])
    check("an identifier from the trusted profile is whitelisted",
          chain._find_untrusted_identifiers("habilitation HAB-IT-2024",
                                            trusted + " HAB-IT-2024") == [])
    check("a contiguous code variant is also flagged",
          chain._find_untrusted_identifiers("merci d'indiquer CODE7731 en tete",
                                            trusted) == ["CODE7731"])
    check("an identifier hidden in a company name is NOT whitelisted anymore",
          chain._find_untrusted_identifiers(
              "Atlas Banque (ref RH-AB-4402)", trusted) == ["RH-AB-4402"])

    print("\n[6] Refusal contract -- proven on the REAL script (exit 2 authority)")
    empty = dict(NOMINAL_LETTER, paragraph_1_intro="")
    res = run_handler(tools["write_cover_letter"], empty)
    check("empty critical paragraph -> is_error (real exit 2)",
          res.get("is_error") is True)
    check("refusal message carries the script's own stderr",
          "Mandatory data missing" in res["content"][0]["text"])
    sentinel = dict(NOMINAL_LETTER, paragraph_2_current=chain.MISSING_SENTINEL)
    res = run_handler(tools["write_cover_letter"], sentinel)
    check("'__MISSING__' sentinel -> is_error (real script honours it)",
          res.get("is_error") is True)
    too_long = dict(NOMINAL_LETTER, paragraph_3_experience="x" * 3000)
    res = run_handler(tools["write_cover_letter"], too_long)
    check("body over 2800 chars -> is_error (one-page cap, real exit 2)",
          res.get("is_error") is True)
    check("cap refusal explains itself (length reported)",
          "2800" in res["content"][0]["text"])
    bad_lang = dict(NOMINAL_LETTER, language="French")
    res = run_handler(tools["write_cover_letter"], bad_lang)
    check("non-ISO language -> is_error from the wrapper guard "
          "(argparse exit-2 collision kept out of the business channel)",
          res.get("is_error") is True and "ISO 639-1" in res["content"][0]["text"])

    print("\n[7] SDK options — least privilege (allow-list)")
    options = chain.build_agent_options()
    check("allowed_tools lists exactly the three custom tools",
          set(options.allowed_tools) == {"mcp__chain__load_job_posting",
                                          "mcp__chain__generate_posting_brief",
                                          "mcp__chain__write_cover_letter"})
    check("tools is an empty allow-list (built-in palette emptied)", options.tools == [])
    check("disallowed_tools retired (allow-list supersedes the deny-list)",
          options.disallowed_tools == [])
    check("model is Haiku", options.model == chain.MODEL)
    check("max_turns == 8", options.max_turns == 8)
    check("max_budget_usd == 0.10", options.max_budget_usd == 0.10)

    print("\n[R] Run telemetry -- RunRecord projection (no agent run, no API)")
    # Two known ResultMessages: a clean success and the max_turns loop. The
    # transform is pure and channel-independent, so these checks run identically
    # for every fixture (they add the same 26 to each fixture's tally).
    success = ResultMessage(
        subtype="success", duration_ms=17000, duration_api_ms=15200,
        is_error=False, num_turns=3, session_id="sess-success",
        stop_reason="end_turn", total_cost_usd=0.046,
        usage={"input_tokens": 1200, "output_tokens": 1699,
               "cache_creation_input_tokens": 4189, "cache_read_input_tokens": 0},
        result="Madame, Monsieur, je suis vivement interesse ...",      # CONTENT
        structured_output={"letter_path": "runs/letter.docx"},          # CONTENT
        permission_denials=[], errors=None)
    rec = chain.record_from_result(success)
    check("subtype mapped", rec.subtype == "success")
    check("is_error mapped", rec.is_error is False)
    check("stop_reason mapped", rec.stop_reason == "end_turn")
    check("num_turns mapped", rec.num_turns == 3)
    check("total_cost_usd mapped (name pinned from SDK source)", rec.total_cost_usd == 0.046)
    check("session_id mapped", rec.session_id == "sess-success")
    check("latency split captured (total + api)",
          rec.duration_ms == 17000 and rec.duration_api_ms == 15200)
    check("harness overhead derivable", rec.duration_ms - rec.duration_api_ms == 1800)
    check("input_tokens from usage dict", rec.input_tokens == 1200)
    check("output_tokens from usage dict", rec.output_tokens == 1699)
    check("cache_creation from usage dict", rec.cache_creation_input_tokens == 4189)
    check("real 0 preserved (not coerced to None)", rec.cache_read_input_tokens == 0)
    _d = asdict(rec)
    check("letter body (result) absent from record", "result" not in _d)
    check("structured_output absent from record", "structured_output" not in _d)
    check("no content string leaks into the serialised line",
          "vivement interesse" not in json.dumps(_d, ensure_ascii=False))

    maxturns = ResultMessage(
        subtype="error_max_turns", duration_ms=33000, duration_api_ms=30000,
        is_error=True, num_turns=9, session_id="sess-loop",
        stop_reason="tool_use", total_cost_usd=0.033,
        usage={"input_tokens": 900, "cache_read_input_tokens": 87000},
        result=None, permission_denials=[],
        errors=["Reached maximum number of turns (8)"])
    rec2 = chain.record_from_result(maxturns)
    check("error run flagged", rec2.is_error is True)
    check("guardrail subtype captured", rec2.subtype == "error_max_turns")
    check("error strings captured verbatim",
          rec2.errors == ["Reached maximum number of turns (8)"])
    check("stop_reason on loop captured", rec2.stop_reason == "tool_use")
    check("empty denials -> count 0", rec2.permission_denials == 0)

    partial = ResultMessage(
        subtype="success", duration_ms=10, duration_api_ms=9, is_error=False,
        num_turns=1, session_id="s", total_cost_usd=None, usage=None)
    rp = chain.record_from_result(partial)
    check("missing cost -> None, no crash", rp.total_cost_usd is None)
    check("missing usage -> token fields None", rp.input_tokens is None)
    check("missing usage key -> None", rp.cache_read_input_tokens is None)

    with tempfile.TemporaryDirectory() as _tmp:
        _log = Path(_tmp) / "runs.jsonl"
        chain.append_jsonl(rec, _log)
        chain.append_jsonl(rec2, _log)
        _lines = _log.read_text(encoding="utf-8").splitlines()
        check("two appends -> two lines", len(_lines) == 2)
        check("line 0 round-trips to the same dict", json.loads(_lines[0]) == asdict(rec))
        check("line 1 is the second record",
              json.loads(_lines[1])["subtype"] == "error_max_turns")

    print("\n" + "-" * 48)
    print("PASSED: " + str(_passed) + "   FAILED: " + str(_failed))
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
