# Tsubame4Agent

Claude Code and Codex plugin for the Institute of Science Tokyo **TSUBAME4.0** —
submit and monitor Grid Engine jobs, manage files on the cluster, and search a
built-in documentation guide, all from the agent.

TSUBAME4 is a GPU-first system: all 240 nodes carry four NVIDIA H100 GPUs each,
and jobs are sized by resource type (`node_f` for a full node, `gpu_1` for a
single GPU, `cpu_*` for CPU-only work) rather than by nodes and cores. This
plugin is a thin machine-specific skin over
[hpc-agent-core](https://github.com/william-dawson/hpc-agent-core): the shared
SSH middleware, PSI/J-style job models, docs-search pipeline, and health checks
live in that package, and this repo supplies only TSUBAME4's facts, its own
Grid Engine scheduler backend (TSUBAME's resource-type dialect doesn't fit
core's ready-made backends — see AGENTS.md), skills, and packaging.

## Configure

Settings live in `~/.hpc-agent/tsubame.json` (the common directory shared by
every hpc-agent-core plugin):

```json
{
  "ssh": {"host": "tsubame"},
  "group": "your-tsubame-group"
}
```

- `ssh.host` is a `~/.ssh/config` alias or `user@hostname` (key-based auth
  required; register your key on the
  [TSUBAME Portal](https://www.t4.cii.isct.ac.jp/en/)).
  `login.t4.gsic.titech.ac.jp` round-robins across the login nodes.
  `TSUBAME_HOST` overrides the file. A legacy `~/.tsubame/config.json` is still
  read if it's the only config present.
- `group` is your TSUBAME group, billed in TSUBAME points via `qsub -g`. A
  JobSpec can override it per job (an explicit empty string forces a free
  trial run); with no group set, jobs submit as free trial runs.
  `TSUBAME_GROUP` overrides the file.

Documentation search is BM25 keyword matching and works fully offline — no
shared embedding endpoint ships for TSUBAME4 (unlike the RIKEN R-CCS machines
in this family), and there is no per-user override for a custom one.

The `tsubame-configuring` skill walks through this interactively.

## Install

### Prerequisite: uv

The plugin starts its MCP servers with `uv tool run` from this repository's
`main` branch, so [`uv`](https://docs.astral.sh/uv/) must be installed and on
your `PATH` before Claude Code or Codex starts the plugin:

```bash
brew install uv        # or: curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart Claude Code or Codex after installing uv so the plugin process inherits
the updated `PATH`.

### Claude Code

```
/plugin marketplace add TengxiangLii/Tsubame4-Agent
/plugin install tsubame@tsubame-marketplace
/reload-plugins
```

### Codex

```
codex plugin marketplace add TengxiangLii/Tsubame4-Agent
```

Then open `/plugins`, install `tsubame`, start a new thread, and run
`/tsubame-demo` to verify the connection end-to-end.

### Manual (any MCP-compatible client)

Both options below only register the MCP servers — copy `plugins/tsubame/skills/`
into wherever your client loads skills from too (this varies by client).

#### Option A — Using Hatch!

[Hatch!](https://github.com/CrackingShells/Hatch) registers MCP servers on any
supported host from a single command. Install it once, then configure both
servers — replace `<host>` with your target platform (`claude-code`, `codex`,
`cursor`, `vscode`, `claude-desktop`, `kiro`, `gemini`, `lmstudio`, or any other
[supported host](https://github.com/CrackingShells/Hatch#supported-mcp-hosts)):

```bash
pip install hatch-xclam

hatch mcp configure tsubame-hpc --host <host> \
  --command uv \
  --args "tool run --quiet --from git+https://github.com/TengxiangLii/Tsubame4-Agent.git@main#subdirectory=server tsubame-hpc-mcp"

hatch mcp configure tsubame-docs --host <host> \
  --command uv \
  --args "tool run --quiet --from git+https://github.com/TengxiangLii/Tsubame4-Agent.git@main#subdirectory=server tsubame-docs-mcp"
```

To replicate the same configuration to additional hosts:

```bash
hatch mcp sync --from-host <host> --to-host cursor,vscode
```

#### Option B — Edit `.mcp.json` directly

Create or edit `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "tsubame-hpc": {
      "command": "uv",
      "args": ["tool", "run", "--quiet", "--from", "git+https://github.com/TengxiangLii/Tsubame4-Agent.git@main#subdirectory=server", "tsubame-hpc-mcp"],
      "env": {}
    },
    "tsubame-docs": {
      "command": "uv",
      "args": ["tool", "run", "--quiet", "--from", "git+https://github.com/TengxiangLii/Tsubame4-Agent.git@main#subdirectory=server", "tsubame-docs-mcp"],
      "env": {}
    }
  }
}
```

## Verify

```bash
uv tool run --quiet --from git+https://github.com/TengxiangLii/Tsubame4-Agent.git@main#subdirectory=server tsubame-doctor
```

All lines should read `✓` except embedding, which reads `!` (not `✗`) — no
shared embedding endpoint is configured for TSUBAME4 at all, so that's
expected, not a problem. Docs search works offline with BM25 regardless.

## Development

```bash
cd server
uv run python -m tsubame_mcp.doctor        # config, SSH, Grid Engine, guide, index, embedding
uv run python tests/smoke.py               # live read-only test over MCP stdio
uv run python tests/smoke.py --job         # + submits a free trial-run job (no points)
uv run python -m tsubame_mcp.ingest --no-embed  # rebuild the docs index after editing the guide
```

See [AGENTS.md](AGENTS.md) for the design rules, cluster facts, and repo map,
and [hpc-agent-core's `PORTING.md`](https://github.com/william-dawson/hpc-agent-core/blob/main/PORTING.md)
for the general porting process this repo follows.

## Documentation

New here? Two guides walk you through using the agent — no prior HPC or agent
experience needed:

- **[Quickstart](QUICKSTART.md)** — install, connect, and run your first (free)
  job in about 5 minutes.
- **[User Guide](docs/USER_GUIDE.md)** — the full manual: how the agent workflow
  works, what you can do, worked examples, a prompt cheat-sheet, and
  troubleshooting.
