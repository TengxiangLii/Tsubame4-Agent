# Tsubame4Agent — Agent Instructions

Claude Code and Codex plugin for the Institute of Science Tokyo TSUBAME4.0
supercomputer: two MCP servers (`tsubame-hpc` for Grid Engine, `tsubame-docs`
for documentation RAG) plus skills. See [README.md](README.md) for the
user-facing overview.

This repo is a **thin machine-specific skin over
[`hpc-agent-core`](https://github.com/william-dawson/hpc-agent-core)** (a PyPI
package). The general porting process this repo follows — the mental model,
the rules, the machine-facts checklist, the config/compute wiring,
validation, and the standing invariants — is documented once, canonically,
in
[hpc-agent-core's `PORTING.md`](https://github.com/william-dawson/hpc-agent-core/blob/main/PORTING.md)
(no copy or stub of it lives in this repo). Read it before changing how this
plugin wires into core. What follows here is only what is specific to *this*
machine.

TSUBAME4 is a **GPU-first** machine: all 240 nodes carry four NVIDIA H100
GPUs. Jobs are sized by **resource type** (a fixed slice of a node), not
nodes/cores — the default is a full node (`node_f`, 4 GPUs). Treat GPUs as
the norm, not an extra.

## Design rules (read before changing code)

- **No write access to `hpc-agent-core`.** Every customization must be
  reachable from this repo: constructor arguments, subclassing, or writing an
  independent equivalent. If you think you need to edit core, re-read the
  relevant module's "Extending this" docstring — you've almost certainly
  misunderstood something.
- **Clarity over cleverness.** A little machine-specific redundancy that reads
  well beats a clever abstraction that doesn't.
- **The `tsubame-hpc` tool surface mirrors the IRI Facility API.** Before
  adding, renaming, or removing a tool, update
  [IRI_CHECKLIST.md](IRI_CHECKLIST.md); new tools should map to an IRI
  endpoint (or be marked an explicit extension). Coverage verdicts are
  machine-specific — re-decide them here, don't copy another machine's (the
  clearest existing example: the allocation endpoints are implemented here
  via `t4-user-info`, since TSUBAME4 has a real per-group points budget,
  unlike a no-accounting Slurm machine that defers them).
- **Tools are thin verbs; workflow knowledge lives in
  `plugins/tsubame/skills/`.** A long docstring telling the model *when* to
  do something belongs in a SKILL.md.
- **All cluster interaction goes through `hpc_agent_core.middleware`** (login
  shell, `$HOME` cwd, base64-quote-proof payloads, 200 KB output cap). Never
  shell out to `ssh` from tool code.
- **Never write to stdout in server code** — the MCP stdio transport uses it
  for JSON-RPC. Log to stderr; middleware already redirects remotemanager's
  stdout.

### §10 invariants (must hold, no exceptions)

- **The MCP server never fails to start.** Missing/malformed config is a
  tool-call-time error pointing at the configuring skill, never a startup
  crash. Nothing at module scope in `config.py`/`compute.py`/`hpc_server.py`
  touches the network or reads the config file eagerly.
- **Bias agent-created files into one visible directory** — job scripts,
  staged uploads, and scratch default under `~/agent/` (the backend's
  `jobs_dir="agent/jobs"` does this; the pre-migration build used the hidden
  `~/.tsubame/jobs/` instead — this changed as part of the migration). Honor
  any explicit path the user gives.
- **Show before you run** — preview the JobSpec / command before `submit_job`
  or `run_command_on_cluster`, unless the user said to just run it.
- **Never invent a documentation URL** — `docs_cite_url` is blank (see
  below), so search results carry no "Source:" line; don't add one in a
  skill or docstring. Pre-migration, every search result cited the same
  top-level TSUBAME Portal URL regardless of which section actually matched
  — not a meaningful per-section source, just a generic homepage pointer —
  so this migration drops it rather than reproducing that pattern.

## Machine wiring (what's specific to TSUBAME4)

- **Scheduler backend** (`server/tsubame_mcp/compute.py`): a full local
  `TsubameBackend(SchedulerBackend)` subclass — TSUBAME4's dialect doesn't
  fit either of core's ready-made backends. Reuses only the
  scheduler-neutral helpers (`duration_to_hms`/`to_epoch`/`parse_exit_code`)
  from `hpc_agent_core.compute.base`; `render_body` is not reusable either,
  since it hardcodes `singularity exec` with no site bind mounts, while
  TSUBAME4 provides **Apptainer** and always bind-mounts `/gs`, `/apps`,
  `/home` — so the body is rendered locally too. This is exactly the
  fallback `PORTING.md` §6 describes for a dialect that doesn't fit: "don't
  force it — subclass `SchedulerBackend` directly... reusing the base
  helpers."
- **Resource-type sizing mapped onto core's shared, machine-agnostic
  models** (not a core edit — machines have no write access to
  `hpc_agent_core.models`):

  | TSUBAME concept | Carried via |
  |---|---|
  | `resource_type` (`node_f`, `gpu_1`, `cpu_40`, ...) | `attributes.custom_attributes["resource_type"]` (default `"node_f"`) |
  | `resource_count` (the `=N` unit count) | `resources.node_count` (PSI/J's "how many of the primary allocation unit" already means the same thing) |
  | `priority` (`-p`) | `attributes.custom_attributes["priority"]` (default `"-5"`) |
  | `array` (`-t`) | `attributes.custom_attributes["array"]` |
  | `hold_jid` (`-hold_jid`) | `attributes.custom_attributes["hold_jid"]` |
  | `gpu_compute_mode` (`-v GPU_COMPUTE_MODE=`) | `attributes.custom_attributes["gpu_compute_mode"]` |
  | queue (`-q`) | `attributes.queue_name` — core field, same purpose, no mapping needed |
  | reservation (`-ar`) | `attributes.reservation_id` — core field, same purpose |
  | group/points (`-g`) | `attributes.account` — core field; already matches TSUBAME's tri-state semantics exactly (`None` → configured default group, `""` → forced free trial run, `"<group>"` → that group) with **no** TSUBAME-specific code needed |
  | wall time (`-l h_rt=`) | `attributes.duration` — core field |
  | env forwarding (`-V`) | `spec.inherit_environment` — core field |
  | OpenMP threads | `resources.cpu_cores_per_process` — core field, used for the `OMP_NUM_THREADS` export |
  | MPI ranks/node (launch-line only, not a scheduler flag) | `resources.processes_per_node` — core field |

  `custom_attributes` (already a `dict[str, str]` on core's `JobAttributes`)
  is the sanctioned escape valve for exactly this kind of machine-specific
  extension — not a workaround.
- **`_has_gpus(resource_type)`** (in `compute.py`) looks up whether a
  resource type provides GPUs from the bundled `resource_types` table in
  `data/tsubame_config.json` — the single source of truth for that fact
  (the pre-migration `models.py` had a *second*, hand-duplicated
  `RESOURCE_TYPES` dict with the same data; this migration collapses that
  to one source).
- **`doctor.py`** can't use `hpc_agent_core.doctor.main()` as-is: core's
  generic `check_ssh()` requires the scheduler probe's stdout to *start
  with* a fixed scheduler-name string (fits Slurm's `sinfo --version` →
  `"slurm ..."`), but Grid Engine's `qstat -help` prints usage text with no
  such predictable prefix — the same shape mismatch Irene's Bridge
  scheduler and cell2026's dual-scheduler port both hit, solved the same
  way each time: reuse core's other `check_*` functions
  (config/guide/docs-index/embedding), write a local SSH+scheduler check.

## Cluster facts

- SSH destination comes from config `ssh.host` (default alias `tsubame`) →
  `login.t4.gsic.titech.ac.jp` (round-robin). Key-based auth only.
- Scheduler is **Altair Grid Engine**: `qsub` (batch), `qrsh`/`iqrsh`
  (interactive), `qstat`, `qacct` (finished jobs), `qdel`. Job scripts use
  `#$` directives; output is `<name>.o<id>` / `<name>.e<id>` in the submit
  dir.
- Nodes are **AMD EPYC 9654 + 4x NVIDIA H100**. Build GPU code with `module
  load cuda`/`nvhpc`; CPU code with `intel` (oneAPI + MKL + Intel MPI).
- **Resource types** (`-l <type>=N`): `node_f` (full, 4 GPU, default),
  `node_h`/`node_q`/`node_o`, `gpu_1`/`gpu_h`, `cpu_4`…`cpu_160`. Max wall 24h.
  One type per job.
- **Groups & points**: jobs are billed to a TSUBAME group via `qsub -g`; the
  default lives in config (`group` / `TSUBAME_GROUP`). No group → free
  **trial run** (≤2 units, 3 min). Check points with
  `t4-user-info group point -g <group>`.
- Storage: `/home` (25 GiB), `/work` (100 GiB, `${HOME/home/work}`), `/gs/fs`
  & `/gs/bs` (group disks), `/local` (per-job node-local NVMe). Lustre.

## hpc-agent-core migration — validation status

`server/tsubame_mcp` was moved onto `hpc-agent-core` (`middleware`, the
shared PSI/J-style models, the docs RAG pipeline, `doctor`'s reusable
checks, and serving glue now come from the package; `config.py`,
`compute.py` — a full local `TsubameBackend` subclass — `hpc_server.py`,
and `data/` remain TSUBAME4-specific) **without any live TSUBAME4 SSH access
available** during this migration:

- **Verified**: package installs/imports cleanly; all 29 MCP tools register
  with zero config present (never-fail-to-start invariant holds); `doctor`
  fails SSH cleanly with a clear message (not a crash), and passes
  config/guide/docs-index checks; embedding correctly `WARN`s (not `FAIL`s)
  since no endpoint is configured for this machine by design.
- **Verified via direct rendering checks** (no live cluster needed —
  `render_script` is pure): reproduced the pre-migration behavior across
  representative cases — default `node_f` + trial run; `gpu_1` with an
  explicit group and an Apptainer container (confirmed `--nv` added, site
  binds present); `node_f` x4 with `array`/`hold_jid`/`gpu_compute_mode`
  all via `custom_attributes`, an explicit queue, and a launcher. All
  produced the expected `#$` directives with no unexpected differences from
  the pre-migration script shape (aside from the intentional
  `agent/jobs/` path change). Also verified `submit()`'s group/trial-run
  tri-state logic and `get_statuses()`'s qstat/qacct parsing directly
  against mocked `run_command` output.
- **Not verified, and should not be assumed working**: an actual `qsub`
  submission, `qstat`/`qacct` output parsing against real (not synthetic)
  TSUBAME4 output, `t4-user-info` output parsing in
  `get_project`/`get_project_allocations`/`get_user_allocations`, and the
  SSH connection path itself. Run `doctor` and `tests/smoke.py --job` (a
  free trial run, no points consumed) for real, from a machine with actual
  TSUBAME4 access, before considering this port finished — per
  `hpc-agent-core`'s `PORTING.md` §9, a clean `doctor` and matching render
  output are not proof of that on their own.
- **Two real, independent bugs found and fixed during this migration** (not
  caused by the hpc-agent-core migration itself, but caught while doing it):
  - The pre-migration `config.py` defined `EMBED_BASE_URL`/`EMBED_MODEL` as
    hardcoded empty string constants, **never read from the config file** —
    but the `tsubame-configuring` skill and `README.md` both explicitly
    instructed users to set `embedding.base_url`/`embedding.model` in their
    config file to enable semantic search. That override never actually
    worked. This migration doesn't resurrect it (core's
    `embed_base_url()`/`embed_model()` are fixed once at `configure()` time
    for every machine in the family, and no other machine supports a
    per-user override either) — the documentation is corrected to stop
    claiming a feature that never functioned, rather than the dead feature
    being reimplemented.
  - `hpc_agent_core.models.map_ge_state` looked like a natural fit to reuse
    for TSUBAME4's `qstat` state parsing (same Grid Engine dialect family as
    cell2026), but it's a **strict dict lookup with no fallback**, covering
    only the codes cell2026's specific AGE deployment has actually
    produced. TSUBAME4's own pre-migration state table is richer (`hRwq`,
    `Rq`, plain `h`/`T`/`d`/`E`) and has a substring-based fallback for any
    code not explicitly listed. Using core's version verbatim would have
    silently misreported several real live-job states as `unknown` —
    caught during behavioral verification, before ever touching a live
    cluster. Fixed by keeping TSUBAME4's own `_map_ge_state()` fully local
    in `compute.py` rather than delegating to core's version — a concrete
    example of "don't force a shared piece that doesn't actually fit,"
    per `PORTING.md`'s own repeated guidance.

## Decisions made under uncertainty

- **`docs_cite_url` left blank**, dropping the pre-migration behavior of
  citing the same top-level TSUBAME Portal URL on every search result
  regardless of which section matched (see the §10 invariants note above).
- **No embedding-endpoint override for TSUBAME4**, matching every other
  machine in the family (fixed at `configure()` time, not user-configurable)
  rather than resurrecting the pre-migration config-file override that
  never worked (see "validation status" above).
- **`_has_gpus()` reads the bundled `resource_types` table** instead of
  keeping a second hand-written `RESOURCE_TYPES` dict (the pre-migration
  `models.py` had both, redundantly) — one source of truth for which
  resource types provide GPUs.

## Documentation search (RAG)

The docs source is **`server/tsubame_mcp/data/tsubame_guide.md`** — an
*original*, plain-language guide (facts in our own words, not the vendor
manual, so the index is freely distributable). It omits generic HPC/compiler
background and anything the agent can read live (`qstat`/`module avail`/
`t4-user-info`). `hpc_agent_core.rag.ingest` chunks it by heading into
`data/docs_index/chunks.json`; rebuild via `python -m tsubame_mcp.ingest
--no-embed` after editing the guide, then commit the index. (`--no-embed`
is effectively always in force for this machine — no embedding endpoint is
configured, so ingest writes a BM25-only index regardless.)

## Repository map

```
.claude-plugin/            Claude Code marketplace manifest
.agents/plugins/           Codex marketplace manifest
plugins/tsubame/           plugin payload for both Claude Code and Codex
  .claude-plugin/          Claude Code plugin manifest
  .codex-plugin/           Codex plugin manifest
  .mcp.json                MCP launch config (uv tool run from the git remote)
  skills/                  tsubame-{configuring,submitting-jobs,
                           monitoring-jobs,reference,demo}
IRI_CHECKLIST.md           API coverage tracker — keep in sync with hpc_server.py
server/
  pyproject.toml           depends on hpc-agent-core (pinned >=0.4,<0.5) + entry points
  run.sh                   local dev launcher for a tsubame_mcp module
  tsubame_mcp/
    config.py              configure() registration + load_cluster_config() +
                           default_group() (TSUBAME-specific points/group policy)
    compute.py             TsubameBackend(SchedulerBackend) — full local subclass;
                           resource-type/priority/array/hold_jid/gpu_compute_mode
                           mapping onto custom_attributes
    hpc_server.py          tsubame-hpc MCP tools (IRI-grouped)
    docs_server.py         tsubame-docs MCP tools (thin over core)
    doctor.py               health checks (custom SSH+GE check; rest thin over core)
    ingest.py               docs-index build entry point (thin over core)
    data/                   tsubame_config.json, tsubame_guide.md, docs_index/
  tests/
    smoke.py                live read-only + optional --job (free trial run) smoke test
QUICKSTART.md              5-minute install/first-job guide (user-facing)
docs/USER_GUIDE.md          full manual: workflow, examples, prompt cheat-sheet
```

Skill names are machine-prefixed so this plugin can be installed alongside
other hpc-agent-core plugins without skill-name collisions.
