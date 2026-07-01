# Tsubame4Agent

Claude Code and Codex plugin for the Institute of Science Tokyo **TSUBAME4.0** — submit and monitor Grid Engine jobs, manage files on the cluster, and search the built-in documentation, all from the agent.

TSUBAME4 is a GPU-first system: all 240 nodes carry four NVIDIA H100 GPUs each, and jobs are sized by resource type (`node_f` for a full node, `gpu_1` for a single GPU, `cpu_*` for CPU-only work) rather than by nodes and cores.

## Install

### Prerequisite: uv

The plugin starts its MCP servers with `uv tool run` from this repository's
`main` branch, so `uv` must be installed and available on your PATH before
Claude Code or Codex starts the plugin.

Common install options:

```bash
brew install uv
```

or:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

After installing uv, restart Claude Code or Codex so the plugin process inherits
the updated PATH.

### Claude Code

Install in Claude Code:

```
/plugin marketplace add TengxiangLii/Tsubame4-Agent
/plugin install tsubame@tsubame-marketplace
/reload-plugins
```

### Codex

Install in Codex:

```
codex plugin marketplace add TengxiangLii/Tsubame4-Agent
```

Then open `/plugins`, install `tsubame`, start a new thread, and run
`/tsubame-demo` to verify the connection end-to-end.

## Configuration

Settings live in `~/.tsubame/config.json`:

```json
{
  "ssh": {"host": "tsubame"},
  "group": "your-tsubame-group"
}
```

- `ssh.host` is a `~/.ssh/config` alias or `user@hostname` (key-based auth required; register your key on the [TSUBAME Portal](https://www.t4.cii.isct.ac.jp/en/)). `login.t4.gsic.titech.ac.jp` round-robins across the login nodes. The env var `TSUBAME_HOST` overrides the file.
- `group` is your TSUBAME group, billed in TSUBAME points via `qsub -g`. A JobSpec can override it per job; with no group set, jobs submit as free trial runs. `TSUBAME_GROUP` overrides the file.

Documentation search ships as a BM25 keyword index and works fully offline — no configuration needed. Only if you have your own embedding endpoint should you add `embedding.base_url`, `embedding.model`, and `embedding.api_key` (via `TSUBAME_EMBED_API_KEY`) and rebuild the index; otherwise search stays on BM25 keyword matching over the same content.
