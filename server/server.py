"""server.py -- agent-candidate nu MCP server. THIS IS WHAT SHIPS.

A standalone stdio MCP server built on the official `mcp` SDK (low-level
`Server`, verified against mcp 1.27.x). It exposes the three candidate-suite
tools wired to chain_core. This is the .mcpb bundle's entry point: Claude Desktop
spawns it as a stdio subprocess and owns the conversation, the agent loop and the
built-in palette.

What this server DELIBERATELY does NOT contain (all of it is CLIENT/DEV side):
  - no agent loop, no Claude Agent SDK, no ClaudeAgentOptions;
  - no allow-list / max_turns / max_budget_usd (the host owns the palette and
    the run budget);
  - no system prompt -- the instructional rampart (axis 3) is the host's system
    prompt, which we cannot set from a tool server;
  - no RunRecord -- run telemetry is harness-side; at deployment the client owns
    the loop, so the server re-feeds observability from tool-side events later.

What it DOES carry is the load-bearing part: the tool-side deterministic
defences, which live in chain_core (ingestion sanitiser, output tripwire, closing
normalisation, profile injection). The tool contracts (name / description /
inputSchema / result text) are imported from chain_core, so the substrate the
model sees here is byte-identical to the one the dev harness observes -- single
source, no drift between observation and deployment.

Low-level (not FastMCP) on purpose: it lets us feed the EXACT same explicit
inputSchema the dev harness uses, instead of re-deriving a schema from type
hints (which would fork the contract). The model-visible contract is the one
thing that must never diverge between the two seams.

Run: `python server.py` (the host normally launches it; the stdout/stdin pipe is
the JSON-RPC transport -- never print to stdout here).
"""

import asyncio
import os
import sys

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import Server

import chain_core as core

server = Server(core.SERVER_NAME, version=core.SERVER_VERSION)


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """The three candidate-suite tools, contracts single-sourced from chain_core.
    Descriptions are built at list time so write_cover_letter's date is current."""
    return [
        types.Tool(
            name=core.LOAD_POSTING_NAME,
            description=core.LOAD_POSTING_DESCRIPTION,
            inputSchema=core.LOAD_POSTING_SCHEMA,
        ),
        types.Tool(
            name=core.BRIEF_NAME,
            description=core.brief_tool_description(),
            inputSchema=core.BRIEF_SCHEMA,
        ),
        types.Tool(
            name=core.LETTER_NAME,
            description=core.letter_tool_description(),
            inputSchema=core.LETTER_SCHEMA,
        ),
        types.Tool(
            name=core.PLAYBOOK_NAME,
            description=core.playbook_tool_description(),
            inputSchema=core.PLAYBOOK_SCHEMA,
        ),
        types.Tool(
            name=core.SUMMARY_NAME,
            description=core.summary_tool_description(),
            inputSchema=core.SUMMARY_SCHEMA,
        ),
        types.Tool(
            name=core.INTERVIEW_NAME,
            description=core.interview_tool_description(),
            inputSchema=core.INTERVIEW_SCHEMA,
        ),
        types.Tool(
            name=core.REFCARD_NAME,
            description=core.refcard_tool_description(),
            inputSchema=core.REFCARD_SCHEMA,
        ),
    ]


def _text(s: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=s)]


def _error(s: str) -> types.CallToolResult:
    # Clean degradation: the same is_error path the dev tools use, so the model
    # receives a refusal it must handle (mirrors {"is_error": True} server-side).
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=s)], isError=True
    )


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Thin dispatch to chain_core. The defences live in the core functions; this
    layer only maps Python exceptions to the MCP clean-error shape, exactly as the
    dev harness maps them to the Agent SDK clean-error dict."""
    if name == core.LOAD_POSTING_NAME:
        try:
            text = core.build_posting_load(
                offer_path=arguments.get("offer_path"),
                offer_body=arguments.get("offer_body"),
            )
        except FileNotFoundError:
            return _error(
                core.OFFER_NOT_FOUND_PREFIX + str(arguments.get("offer_path"))
            )
        except ValueError as e:
            return _error(str(e))
        return _text(core.POSTING_RESULT_PREFIX + text)

    if name == core.BRIEF_NAME:
        try:
            path = core.build_brief(arguments)
        except ValueError as e:
            return _error(str(e))
        return _text(core.BRIEF_RESULT_PREFIX + path + core.output_dir_notice())

    if name == core.LETTER_NAME:
        try:
            path = core.build_letter(arguments)
        except ValueError as e:
            return _error(str(e))
        return _text(core.LETTER_RESULT_PREFIX + path + core.output_dir_notice())

    if name == core.PLAYBOOK_NAME:
        try:
            path = core.build_playbook(arguments)
        except ValueError as e:
            return _error(str(e))
        return _text(core.PLAYBOOK_RESULT_PREFIX + path + core.output_dir_notice())

    if name == core.SUMMARY_NAME:
        try:
            path = core.build_summary(arguments)
        except ValueError as e:
            return _error(str(e))
        return _text(core.SUMMARY_RESULT_PREFIX + path + core.output_dir_notice())

    if name == core.INTERVIEW_NAME:
        try:
            path = core.build_interview(arguments)
        except ValueError as e:
            return _error(str(e))
        return _text(core.INTERVIEW_RESULT_PREFIX + path + core.output_dir_notice())

    if name == core.REFCARD_NAME:
        try:
            path = core.build_refcard(arguments)
        except ValueError as e:
            return _error(str(e))
        return _text(core.REFCARD_RESULT_PREFIX + path + core.output_dir_notice())

    return _error("Unknown tool: " + str(name))


async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


if __name__ == "__main__":
    # Self-re-exec / redispatch guard (frozen binary). If we were spawned as
    # `<binary> --run <kind> ...`, run the candidate-suite script and exit HERE,
    # BEFORE starting the MCP server -- otherwise the child would start a second
    # server (recursive spawn). A normal launch carries no --run and proceeds.
    core.dispatch_suite_run(sys.argv[1:])
    asyncio.run(main())
    # asyncio.run returns once the host closes stdin (EOF) and server.run
    # completes: the server contract is fully discharged and every JSON-RPC reply
    # has already been flushed by the transport (it flushes per message). Exit via
    # os._exit instead of falling through to interpreter shutdown, where two
    # teardown hazards live -- both AFTER the result, neither a real failure:
    #   - anyio runs the stdin readline() in a worker thread that can still be
    #     parked on the now-closed stdin handle and raise at finalization;
    #   - the transport wrapped sys.stdout in a TextIOWrapper whose finalizer
    #     closes the underlying buffer, so sys.stdout is ALREADY closed here --
    #     touching it (even a flush) raises `ValueError: I/O operation on closed
    #     file`. So we deliberately do NOT flush; there is nothing of ours left to
    #     flush anyway.
    # os._exit is a raw _exit syscall: it runs no finalizers (none matter -- no
    # atexit, the host owns lifecycle) and touches no std stream, so neither hazard
    # fires. A genuine failure during the run propagates out of asyncio.run ABOVE
    # this line, so real crashes still exit non-zero with their traceback.
    os._exit(0)
