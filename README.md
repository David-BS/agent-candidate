# agent-candidate

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**A security-first, agentic rebuild of a deterministic job-application suite.**
It opens the *composition* channel its predecessor deliberately lacked — an agent
decides which tool to call and in what order, and tailors the output — under an
explicit threat model. It ships as an installable MCP bundle for Claude Desktop.

---

## What this is

The predecessor (`candidate-suite`) is a deterministic Python suite that
generates job-application deliverables (cover letter, interview prep, summary,
playbook, reference card, tracking) from templates and scripts: reliable, but it
composes nothing. This project deliberately opens the composition channel: an
agent decides which tool to call, in what order, and tailors the output.

The agentic layer does not throw away the predecessor's robustness. The real
`candidate-suite` scripts remain the deterministic source of truth (validation
by exit code, "never invent a missing field" wired in); the agent only decides
*which* script to run and *in what order*, while a deterministic floor keeps
holding underneath.

The project doubles as a learning curriculum: every mechanism (tool palettes,
prompt-injection defenses, output validation, cost control) is built with
single-variable experiments, pre-stated success criteria, and behavioral
evidence from live runs, before being trusted.

---

## Architecture

The shipped artifact is a **standalone stdio MCP server** built on the official
`mcp` SDK (`mcp.server.lowlevel.Server`) — not an in-process server. The host
(Claude Desktop) spawns it as a stdio subprocess and is the MCP client.

- **Single-source tool contract.** Tool name, description, input schema, and
  result strings live once in `server/chain_core.py` and are read by every seam
  (server, dev harness, manifest), so there is no drift between what the model
  observes and what ships. The manifest is a *verified projection* of that
  contract (a parity check fails the build if they diverge).
- **Deterministic core preserved.** The server does not reimplement the suite.
  Under the frozen binary it re-executes the pinned `candidate-suite` scripts as
  a separate process (self-re-exec / argv dispatch), so the deterministic suite
  runs byte-for-byte as before, behind a clean process boundary.
- **Self-contained binary.** The server is frozen with PyInstaller (onedir,
  UTF-8 baked in) so the target machine needs **no Python install** — the binary
  carries its own interpreter and platform dependencies.

---

## Scope & compatibility

agent-candidate is built for the **Anthropic Claude ecosystem** and runs as a
local MCP server under **Claude Desktop**, which spawns it as a stdio
subprocess and owns its lifecycle, secrets, and updates. It is a **distributed
artifact, not a hosted service**: everything runs locally on your machine,
single-tenant.

| Target | Platform |
|---|---|
| `win-x64` | Windows (x64) |
| `mac-arm64` | macOS (Apple silicon) |
| `mac-x64` | macOS (Intel) |

The binary is self-contained, so **no Python install is required** on the target
machine. **Linux is intentionally unsupported**: there is no Claude Desktop host
for it (a Linux build runs in CI only, as a portability canary).

---

## Download & install

> **Requirements:** Claude Desktop (macOS or Windows). No coding or local Python
> setup required.

1. Go to the [**latest release**](https://github.com/David-BS/agent-candidate/releases/latest).
2. Download the `.mcpb` asset **for your platform** (architecture matters — an
   Intel bundle will not run on Apple silicon and vice versa).
3. Open it in Claude Desktop; the host validates the manifest and registers the
   server, which exposes three tools: `load_job_posting`,
   `generate_posting_brief`, `write_cover_letter`.

Full steps, the unsigned-binary first-launch prompt, and the deployment-time
security scope are in [`INSTALL.md`](./INSTALL.md).

---

## Security posture

Read [`THREAT_MODEL.md`](./THREAT_MODEL.md). In short:

- **Trust boundary:** instructions come only from the operator; everything
  entering through a tool result — including the entire job offer — is data,
  never instructions.
- **Layered defenses, paired per channel:** deterministic/structural defenses
  carry the load wherever a channel can be removed (ingestion strip, empty
  built-in tool palette, identifier-taint output tripwire); judgment covers only
  what must remain open.
- **Documented residue:** where a channel is deliberately left under a weaker
  defense, that is recorded as an engineering decision with a stated damage
  ceiling and a re-evaluation trigger — not left implicit. The deployment-time
  scope of that residue is stated in [`INSTALL.md`](./INSTALL.md).

---

## Observability

Run accounting (metadata only — content is excluded by design, so the log can
never become a PII sink) is described in [`OBSERVABILITY.md`](./OBSERVABILITY.md):
the record → attribution → aggregation model, dev-side.

---

## Data discipline

All fixtures, examples, and test data are **fictional** (fictional companies,
postings, identifiers). No real employer or candidate data is ever used in this
repository, its history, or its test runs. Run records are written under
`runs/`, which is git-ignored, and never contain deliverable content.

---

## Engineering gates

`main` is protected; every change clears the CI/CD gates before merge:

- **CI** — `ruff check` + `ruff format --check` + a compile sweep (`server lab`).
- **Floor** — the deterministic floor suite, run as a script (exit 0/1, not
  pytest), against the `candidate-suite` scripts pinned at an immutable SHA.
- **Security** — Bandit (with documented skips) on the shipped `server/` code.
- **CodeQL** — `security-extended` analysis.
- **Server Smoke** — a live stdio MCP server boot/handshake check, the
  regression guard for the server seam the floor cannot reach.
- **release** — per-platform frozen-binary build + proof, then `.mcpb` assembly.

Dependencies are pinned and watched by Dependabot (`github-actions` + `pip`).

The full pipeline rationale — what each gate enforces, the per-seam testing
model and the three delivery-acceptance bars, the `candidate-suite` pin and its
drift watcher, and the Layer A / Layer B fork model — lives in
[`CI_CD.md`](CI_CD.md).

---

## Repository layout

```
.
├── README.md
├── CONTRIBUTING.md           # how to propose a change and reproduce the gates locally
├── LICENSE
├── THREAT_MODEL.md           # threat model: channels × paired defenses (review triggers in §8)
├── OBSERVABILITY.md          # run-record / attribution / aggregation model (dev-side)
├── INSTALL.md                # install matrix, steps, and published security scope
├── CI_CD.md                  # CI/CD deep-dive: gates, testing model, Layer A/B, the why
├── manifest.json             # MCP bundle manifest (server.type: binary; verified tool contract)
├── pyproject.toml            # ruff + bandit config (single source for the toolchain)
├── requirements.txt          # pinned runtime / floor / build dependencies
├── requirements-build.txt    # pinned build-only toolchain (PyInstaller, tzdata, …)
├── .mcpbignore               # non-runtime exclusions for the .mcpb bundle
├── server/                   # what ships: the standalone stdio MCP server
│   ├── server.py             # stdio MCP server + early argv dispatch (anti recursive-spawn guard)
│   └── chain_core.py         # single-source tool contract + deterministic tool logic + self-re-exec
├── packaging/
│   └── agent-candidate.spec  # PyInstaller spec (onedir, -X utf8, hiddenimports)
├── lab/                      # dev-side only — never ships in the bundle
│   ├── brief_to_letter_chain.py  # phase-3 agentic pipeline (harness)
│   ├── aggregate_runs.py         # run-record aggregation (dev observability)
│   ├── raw_agent_loop.py         # phase 2: agent loop hand-rolled on the raw API
│   ├── agent_sdk_loop.py         # phase 2: same task, Claude Agent SDK
│   ├── test_chain_tools.py       # deterministic floor suite (script, exit 0/1)
│   ├── test_frozen_build.py      # frozen-binary proof (runs the real exe)
│   ├── test_frozen_server.py     # frozen stdio-server boot/handshake proof (JSON-RPC)
│   ├── test_split_parity.py      # dev ↔ ship parity proof
│   └── fixtures/                 # fictional postings, injection probes included
└── .github/
    ├── dependabot.yml            # github-actions + pip ecosystems
    └── workflows/                # ci · floor · security · codeql · server-smoke · release
```

---

## Build & release (for maintainers)

Build the self-contained binary locally (PyInstaller output is git-ignored):

```bash
pip install -r requirements.txt -r requirements-build.txt
pyinstaller --noconfirm --clean packaging/agent-candidate.spec
# -> a per-platform onedir under dist/, with the frozen server binary
```

Cut a release — the `release` workflow builds the per-platform binaries, proves
each frozen artifact, assembles one `.mcpb` per target, and attaches them to the
Releases page (a version guard refuses to publish if the tag and the manifest
version disagree):

```bash
# 1. bump `version` in manifest.json
# 2. tag and push
git tag v0.1.0
git push origin v0.1.0
```

Builds are native per architecture (`lxml` is a C-extension with no reliable
universal2 wheel); there is no `lipo`/universal binary.

---

## License

Released under the [MIT License](LICENSE). You're free to use, modify, and share
it; attribution is appreciated.
