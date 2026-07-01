# Tsubame4Agent — agent instructions

Claude Code and Codex plugin for the Institute of Science Tokyo TSUBAME4.0
supercomputer: two MCP servers (`tsubame-hpc` for Grid Engine, `tsubame-docs` for
documentation RAG) plus skills. See README.md for the user-facing overview.

TSUBAME4 is a **GPU-first** machine: all 240 nodes carry four NVIDIA H100 GPUs.
Jobs are sized by **resource type** (a fixed slice of a node), not nodes/cores —
the default is a full node (`node_f`, 4 GPUs). Treat GPUs as the norm, not an
extra.

## Design rules (read before changing code)

- **The `tsubame-hpc` tool surface mirrors the IRI Facility API** (DOE standard).
  The reference spec is **not committed** (it is ALCF's, no redistribution
  license); fetch a working copy when needed —
  `curl -s https://api.alcf.anl.gov/openapi.json -o openapi.json` (git-ignored).
  Before adding/renaming/removing a tool, check `IRI_CHECKLIST.md` and keep it in
  sync. Extensions with no IRI counterpart (like `run_command_on_cluster`) are
  allowed but must be marked as such. Coverage verdicts are **machine-specific**
  (e.g. the allocation endpoints are implemented here via `t4-user-info`, unlike
  the GPU-first reference port); see PORTING.md.
- **All cluster interaction goes through `server/tsubame_mcp/middleware.py`**
  (`run_command` / `write_remote_file`). Never shell out to ssh directly from
  tool code. Middleware enforces three conventions in one place: commands run
  under a **login shell** (Grid Engine resolves through the login profile), the
  working directory is **$HOME**, and payloads travel **base64-encoded**
  (quote-proof). Output is capped at 200KB.
- **Never write to stdout in server code** — the MCP stdio transport uses it for
  JSON-RPC and any stray print corrupts the session. Log to stderr; remotemanager
  progress is redirected by middleware.
- **Tools are thin verbs; workflow knowledge lives in
  `plugins/tsubame/skills/`.** A long docstring telling the model *when* to act
  belongs in a SKILL.md instead.
- **The MCP runtime must be self-contained under `server/`.** `plugins/tsubame/
  .mcp.json` launches the servers with `uv tool run --from
  git+https://…@main#subdirectory=server`. Do not depend on `CLAUDE_PLUGIN_ROOT`,
  Codex root variables, or repo-root `data/` paths at runtime. Anything the server
  needs after uv installation must be package data under
  `server/tsubame_mcp/data/`.
- **`models.py` is PSI/J-shaped but adapted to TSUBAME4 resource types** — the
  ResourceSpec carries `resource_type` + `resource_count` (not node/ntasks/cpus),
  because cores/memory/GPUs are fixed by the type. Deviations are listed at the
  bottom of `IRI_CHECKLIST.md`.
- Bias to simple and maintainable. No new runtime dependencies without a strong
  reason (current set: mcp, remotemanager, httpx, numpy). Python ≥ 3.10.

## Cluster facts

- SSH destination comes from `~/.tsubame/config.json` (`ssh.host`, default alias
  `tsubame`) → `login.t4.gsic.titech.ac.jp` (round-robin). Key-based auth only.
- Scheduler is **Altair Grid Engine**: `qsub` (batch), `qrsh`/`iqrsh`
  (interactive), `qstat`, `qacct` (finished jobs), `qdel`. Job scripts use `#$`
  directives; output is `<name>.o<id>` / `<name>.e<id>` in the submit dir.
- Nodes are **AMD EPYC 9654 + 4× NVIDIA H100**. Build GPU code with `module load
  cuda`/`nvhpc`; CPU code with `intel` (oneAPI + MKL + Intel MPI).
- **Resource types** (`-l <type>=N`): `node_f` (full, 4 GPU, default), `node_h`/
  `node_q`/`node_o`, `gpu_1`/`gpu_h`, `cpu_4`…`cpu_160`. Max wall 24h. One type
  per job.
- **Groups & points**: jobs are billed to a TSUBAME group via `qsub -g`; the
  default lives in config (`group` / `TSUBAME_GROUP`) and is injected by
  `compute.py`. No group → free **trial run** (≤2 units, 3 min). Check points with
  `t4-user-info group point -g <group>`.
- Storage: `/home` (25 GiB), `/work` (100 GiB, `${HOME/home/work}`), `/gs/fs` &
  `/gs/bs` (group disks), `/local` (per-job node-local NVMe). Lustre.

## Documentation search (RAG)

The docs source is **`server/tsubame_mcp/data/tsubame_guide.md`** — an *original*,
plain-language guide written for users working through the agent (facts in our own
words, not a copy of the vendor manual, so the index is freely distributable). It
deliberately omits generic HPC/compiler background and anything the agent can read
live (`qstat`/`module avail`/`t4-user-info`); keep it that way when editing.
`rag/ingest.py` chunks it by markdown heading into
`server/tsubame_mcp/data/docs_index/chunks.json` (section text + breadcrumbs, also
the BM25 corpus), committed as package data.

Search is **BM25 keyword matching by default** — TSUBAME4 is at Institute of
Science Tokyo, so no embedding endpoint ships with the plugin (`EMBED_BASE_URL` /
`EMBED_MODEL` in `config.py` are empty). BM25 works fully offline. To enable
semantic search, set those constants to a reachable endpoint + model, set an API
key, and rebuild: `python -m tsubame_mcp.rag.ingest` (commit the new
`embeddings.npy`). The committed `embeddings.npy`, if any, is tied to its exact
model — never make the model user-configurable.

**To rebuild the index** (after editing the guide): `python -m
tsubame_mcp.rag.ingest --no-embed` (BM25). Commit the regenerated `chunks.json`.

## Development workflow

```bash
cd server
python3 -m venv .venv && .venv/bin/pip install -e .   # or just use ./run.sh
./run.sh tsubame_mcp.doctor            # validate config, SSH, Grid Engine, index
.venv/bin/python tests/smoke.py        # live read-only test over MCP stdio
.venv/bin/python tests/smoke.py --job  # + submits a free trial-run job (no points)
.venv/bin/python -m tsubame_mcp.rag.ingest --no-embed  # rebuild docs index
```

- The smoke tests need working cluster access. `--job` uses a free trial run, so
  it consumes no points. Run the read-only test for most changes; run `--job` when
  touching `compute.py`, `middleware.py`, or `models.py`.
- Validate the install-path runtime with: `uv tool run --quiet --from ./server
  tsubame-doctor`. The marketplace runtime uses the same package boundary, from
  GitHub `main`.
- User settings live in `~/.tsubame/config.json` (may contain an embedding API
  key — never commit it, never echo the key). The `tsubame-configuring` skill
  documents the schema.

## Repository map

```
.claude-plugin/         Claude Code marketplace manifest
.agents/plugins/        Codex marketplace manifest
plugins/tsubame/        plugin payload for both Claude Code and Codex
  .claude-plugin/       Claude Code plugin manifest
  .codex-plugin/        Codex plugin manifest
  .mcp.json             shared MCP launch config (uv tool run from main)
  skills/               tsubame-configuring, tsubame-submitting-jobs,
                        tsubame-monitoring-jobs, tsubame-reference, tsubame-demo
IRI_CHECKLIST.md        API coverage tracker — keep in sync with hpc_server.py
server/tsubame_mcp/
  data/                 packaged guide, static facts, and docs_index
  middleware.py         SSH layer — the only place that talks to the cluster
  models.py             PSI/J-style schemas + Grid Engine state normalization
  compute.py            JobSpec → qsub script, qstat/qacct parsing, group fallback
  hpc_server.py         tsubame-hpc MCP tools (IRI-grouped)
  docs_server.py        tsubame-docs MCP tools
  rag/                  embed client / index store / markdown ingest pipeline
  doctor.py             health checks (python -m tsubame_mcp.doctor)
  serving.py            shared CLI entry point
```

Skill names are machine-prefixed so this and sibling plugins can be installed at
once without skill-name collisions.
