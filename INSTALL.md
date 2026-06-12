# Installing `agent-candidate`

`agent-candidate` is distributed as an **MCP Bundle (`.mcpb`)** that you open in
**Claude Desktop**. The bundle carries a self-contained binary, so the machine
needs **no Python install**: the host spawns the server as a stdio subprocess
and owns its lifecycle, secrets, and updates.

This is a distributed artifact, not a hosted service. Everything runs locally on
your machine, single-tenant.

## Supported targets

| Target | Platform | Bundle |
|---|---|---|
| Windows (x64) | `win32` | `agent-candidate-win-x64.mcpb` |
| macOS (Apple silicon) | `darwin` arm64 | `agent-candidate-mac-arm64.mcpb` |
| macOS (Intel) | `darwin` x64 | `agent-candidate-mac-x64.mcpb` |

Linux is not supported: Claude Desktop has no Linux host, so a Linux bundle
would have nowhere to run. (A Linux build exists in CI only, as a portability
canary.)

If your platform is not in the table, there is no supported path; building from
source is the manual fallback (see the repository's build workflow), but it is
not a supported install.

## Install steps

1. Download the `.mcpb` for your platform from the project's
   [GitHub Releases](https://github.com/David-BS/agent-candidate/releases).
   Match the target exactly (architecture matters — an Intel bundle will not run
   on Apple silicon and vice versa).
2. Open the file in **Claude Desktop** (double-click, or use the host's
   "install extension / bundle" entry). The host validates the manifest and
   registers the server.
3. The server exposes three tools: `load_job_posting`,
   `generate_posting_brief`, and `write_cover_letter`.

### First-launch security prompt (unsigned binary)

The binaries are **not code-signed or notarized** in this release. On first
launch the OS may warn about an unidentified developer:

- **macOS (Gatekeeper):** you may need to allow the binary explicitly in
  *System Settings → Privacy & Security* before the host can spawn it.
- **Windows (SmartScreen):** you may see a "Windows protected your PC" prompt;
  choose *More info → Run anyway* to proceed.

If the host cannot spawn the binary because of OS quarantine, that is the
expected blocker for an unsigned artifact, not a bug in the bundle.

## Security scope at deployment

The full analysis is in [`THREAT_MODEL.md`](./THREAT_MODEL.md). One point is
specific to installed use and is stated here explicitly, because a documented
residue is an engineering decision and a silent one is a hole.

**What still holds when installed:**

- The built-in tool palette is empty by construction (allow-list). The only
  tools are this server's three; there is **no network egress, no shell, no file
  read beyond the designed inputs**.
- The deterministic defenses ship **inside the server**: the ingestion strip
  (non-rendered offer content removed before the model sees it) and the
  identifier-taint output tripwire. These are not host-dependent.
- The cover letter is, by the nature of its use, **read by its author before
  being sent** — a structural human-in-the-loop the domain supplies for free.

**What is not present when installed:**

- The **instructional rampart** — the hardened system-prompt clause that, in the
  lab, raised the model's resistance to low-salience injected instructions in
  *visible* offer prose — **does not ship**. At install time the host owns the
  system prompt, so that clause is not guaranteed to be present.
- Consequently, the **visible-prose channel** at deployment is held by the
  shipped deterministic defenses **plus the host's own judgment plus the
  author's native review of the letter** — not by an instructional rampart from
  this server.

**Damage ceiling, unchanged:** with an empty palette and an author-reviewed
artifact, the worst credible outcome is a *defective draft submitted to a human
eye*, never an executed action or an exfiltration of data the operator did not
already place in scope.

## Data discipline

All fixtures and examples are **fictional**. No real employer or candidate data
is used. When you use the tools, the candidate profile and job offer you supply
stay on your machine.
