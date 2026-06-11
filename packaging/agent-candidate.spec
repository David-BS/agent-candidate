# -*- mode: python ; coding: utf-8 -*-
# agent-candidate.spec -- PyInstaller build recipe for the frozen MCP server.
#
# WHY onedir (NOT onefile): the server self-re-execs once per candidate-suite
# call (under freeze, the binary is its own interpreter: `<binary> --run <kind>`).
# With onefile, every re-exec re-extracts the whole archive to a temp dir; a
# brief + a letter = three full extractions per request. onedir reads its libs
# from _internal/ on disk -- no extraction, fast cold start. The .mcpb bundle is
# a directory anyway, so onefile's single-file convenience buys nothing here.
#
# WHY explicit hiddenimports: candidate-suite's scripts run via runpy INSIDE this
# binary, so their imports are invisible to PyInstaller's static analysis of
# server.py / chain_core.py. They must be named here or the binary builds fine
# and then crashes at first real invocation with ModuleNotFoundError.
#
# THE LOOP (test-driven, by design): if the smoke-test (lab/test_frozen_build.py)
# reports a missing module, the error names it -- add it to `hidden` below and
# rebuild. The build failure is the source; we read it, we do not guess it.
#
# Build (repo root, in the venv):  pyinstaller packaging/agent-candidate.spec
# Output (onedir):                 dist/agent-candidate/agent-candidate(.exe)

import os

# SPECPATH is the directory holding this .spec (injected by PyInstaller).
# packaging/ sits at the repo root, so the root is its parent. Anchoring on
# SPECPATH makes the build independent of the current working directory.
ROOT = os.path.dirname(SPECPATH)
SERVER = os.path.join(ROOT, "server")

hidden = [
    # python-docx: fill_cover_letter.py renders the .docx via this package.
    "docx",
    # lxml: python-docx's XML backend (its C extension + submodules). The
    # hooks-contrib hook usually completes this; named here as a safety net.
    "lxml",
    # tzdata: zoneinfo has NO system tz database on Windows, and the brief
    # script builds its capture date from --timezone (e.g. Europe/Paris). This
    # one CANNOT be auto-discovered: zoneinfo is imported by candidate-suite,
    # which is invisible to the static analysis. It must be explicit.
    "tzdata",
]

a = Analysis(
    [os.path.join(SERVER, "server.py")],
    pathex=[SERVER],          # so `import chain_core` resolves
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# Bake `-X utf8` (PEP 540 UTF-8 mode) INTO the binary. WHY: a frozen Windows
# binary defaults its stdio to cp1252, which cannot encode the candidate-suite
# success glyph (U+2705 check mark) the scripts print -> crash on success. The
# host (Claude Desktop) will NOT set PYTHONUTF8 for us at deployment, and the
# frozen bootloader ignores that env var anyway, so the encoding must be the
# binary's OWN property: a self-contained artifact configures its own runtime.
# Neutral for the MCP server path (the stdio transport uses the binary buffer,
# not the text layer).
runtime_options = [("X utf8", None, "OPTION")]

exe = EXE(
    pyz,
    a.scripts,
    runtime_options,
    exclude_binaries=True,    # onedir: libraries are collected separately
    name="agent-candidate",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,             # stdio MCP server: it needs a real stdin/stdout
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="agent-candidate",
)
