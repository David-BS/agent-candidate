# agent-candidate

A security-first, agentic rebuild of a deterministic job-application suite —
built as a structured learning project on agentic AI design.

## What this is

The predecessor (`candidate-suite`) is a deterministic Python suite that
generates job-application deliverables (cover letter, interview prep, summary,
playbook, reference card, tracking) from templates and scripts: reliable, but
it composes nothing. This project deliberately opens the composition channel:
an agent (Claude Agent SDK, in-process MCP server) decides which tools to call,
in what order, and writes tailored output — under an explicit threat model.

The project doubles as a learning curriculum: every mechanism (tool palettes,
prompt-injection defenses, output validation, cost control) is built with
single-variable experiments, pre-stated success criteria, and behavioral
evidence from live runs, before being trusted.

## Status

**Lab phase.** The code in `lab/` is the experimental harness
(`brief_to_letter_chain`): a brief-to-cover-letter pipeline using simplified
tool doubles that are contract-faithful to the real suite's scripts. The graft
onto the real scripts is the next milestone — see the threat model's review
trigger §8.5, which governs that swap.

## Security posture

Read [`THREAT_MODEL.md`](./THREAT_MODEL.md). In short:

- **Trust boundary:** instructions come only from the operator; everything
  entering through a tool result — including the entire job offer — is data,
  never instructions.
- **Layered defenses, paired per channel:** deterministic/structural defenses
  carry the load wherever a channel can be removed (ingestion strip, empty
  built-in tool palette, output tripwire); judgment covers only what must
  remain open.
- **Documented residue:** where a channel is deliberately left under a weaker
  defense, that is recorded as an engineering decision with a stated damage
  ceiling and a re-evaluation trigger — not left implicit.

## Data discipline

All fixtures, examples, and test data are **fictional** (fictional companies,
postings, identifiers). No real employer or candidate data is ever used in
this repository, its history, or its test runs.

## Repository layout

```
.
├── README.md
├── LICENSE
├── THREAT_MODEL.md     # living document — review triggers in its §8
└── lab/                # experimental harness (current implementation)
    ├── brief_to_letter_chain.py  # brief→letter agentic pipeline (current)
    ├── test_chain_tools.py       # deterministic floor suite
    ├── raw_agent_loop.py         # phase 2: the agent loop, hand-rolled on the raw API
    ├── agent_sdk_loop.py         # phase 2: same task, Claude Agent SDK
    └── fixtures/                 # fictional job postings (injection probes included)
```

## License

MIT — see [`LICENSE`](./LICENSE).
