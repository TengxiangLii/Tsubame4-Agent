# IRI Facility API coverage — TSUBAME4

Endpoint-by-endpoint coverage decisions for `server/tsubame_mcp/hpc_server.py`
against the IRI (Integrated Research Infrastructure) Facility API. This is
genuinely machine-specific (what's sensible on TSUBAME4 may not be on another
machine) and intentionally lives here rather than in `hpc-agent-core`.

**The verdicts below are specific to TSUBAME4.** They were decided against
what TSUBAME4 can actually do, not inherited from another machine in this
family — the clearest example: the allocation endpoints are **implemented**
here (TSUBAME4 exposes a per-group TSUBAME-points budget via `t4-user-info
group point`), unlike a no-accounting Slurm machine (e.g. cell2026's Slurm
side) which defers them for lack of accounting. When porting onward,
re-decide every row from scratch.

## Facility / resources

| IRI endpoint | Tool | Status |
|---|---|---|
| `GET /facility` | `get_facility` | Implemented — returns the full bundled `tsubame_config.json` (resource types, modules, storage). Static. |
| `GET /resources` | `get_resources` | Implemented — live per-queue slot summary (used/reserved/available/total) from `qstat -g c`, plus the static resource-type table. Only one resource, `tsubame4`. |
| `GET /resources/{name}` | `get_resource` | Implemented, same detail for the single resource. |

## Projects / accounting

TSUBAME4 exposes a real per-group points budget, so this section is fully
implemented — unlike a no-accounting machine where it would be deferred:

| IRI endpoint | Tool | Status |
|---|---|---|
| `GET /account/projects` | `get_projects` | Implemented — TSUBAME groups from `id -Gn`, filtered to the `tg*` project groups (system groups like `tsubame-users`/`tgz-edu` excluded). Each usable as `attributes.account` (`qsub -g`). |
| `GET /account/projects/{id}` | `get_project` | Implemented — group detail including point balance. |
| `GET .../project_allocations`, `GET .../project_allocations/{id}` | `get_project_allocations` | Implemented — `t4-user-info group point -g <group>` returns deposit + remaining TSUBAME points. No batch form. |
| `GET .../user_allocations`, `GET .../user_allocations/{id}` | `get_user_allocations` | Implemented — point balance for each of the current user's groups. No batch-by-id form (returns all groups; use `get_project_allocations` for a single group). |

## Compute

| IRI endpoint | Tool | Status |
|---|---|---|
| `POST /compute/job/{resource_id}` | `submit_job` | Implemented. Sizes via `attributes.custom_attributes["resource_type"]` (default `node_f`) and `resources.node_count`; bills to `attributes.account` (the `-g` group — `None` uses the configured default, `""` forces a free trial run, `"<group>"` charges that group explicitly). Returns `{job_id, script_path, group}`. |
| `GET /compute/job/{id}` | `get_job_status` | Implemented — `qstat` (live) with `qacct` fallback for finished jobs. |
| `POST /compute/status/{resource_id}` | `get_job_statuses` | Implemented; empty list = the current user's live (queued + running) jobs. |
| `DELETE /compute/cancel/{id}` | `cancel_job` | Implemented — `qdel` + post-cancel state report. |
| `PUT /compute/job/{id}` | `update_job` | Implemented via `qalter` — time_limit/name/priority/hold_jid, mostly queued-only. |

## Filesystem

All of `fs_ls`, `fs_stat`, `fs_view`, `fs_head`, `fs_tail`, `fs_mkdir`,
`fs_upload`, `fs_download`, `fs_checksum`, `fs_cp`, `fs_mv`, `fs_chmod`,
`fs_chown`, `fs_symlink`, `fs_compress`, `fs_extract` are implemented as thin
wrappers over `hpc_agent_core.middleware` (`run_command`, `quote_path`,
`upload_file`, `download_file`) or direct shell one-liners.

`fs_upload`/`fs_download` **changed shape during the hpc-agent-core
migration**: the pre-migration version passed file content inline through
the MCP tool call (`fs_upload(path, content, binary=False)`, base64 for
binary; `fs_download(path)` returned base64, capped at 5 MB to match the IRI
spec literally). This is now `fs_upload(path, local_path)` /
`fs_download(path, local_path=None)`, transferring via rsync (scp fallback
if rsync < 3.0) with no size limit, matching every other machine in this
family — the base64-through-MCP shape fails past a few KB (token-per-byte
overhead in the tool response), which the 5 MB cap was working around at the
cost of a hard ceiling. Deliberately diverges from IRI's literal
multipart/base64 shape for the same reason every other machine's does.

## Extensions (no IRI counterpart)

| Tool | Why it exists |
|---|---|
| `run_command_on_cluster` | Arbitrary login-shell command (e.g. `module avail`, `t4-user-info`, `qstat`). Documented as "show before you run," same as `submit_job`. |

## Not implemented

- **`GET /status/incidents`, `/status/events`** (and their `/{id}` forms): no
  machine-readable incident/maintenance feed exposed on the login node; users
  check the TSUBAME Portal.
- **`GET /account/capabilities`**: no equivalent concept exposed on TSUBAME4.
- **`GET /task/...`**: IRI's async-task model queues REST operations; our SSH
  execution is synchronous (`qsub` completes before we return), so
  `submit_job` returns `{job_id, script_path, group}` directly — no task
  polling needed.
- **Interactive jobs** (`qrsh`/`iqrsh`): inherently need a live terminal
  session, which doesn't fit this agent's request/response tool model. The
  `tsubame-submitting-jobs` skill documents the interactive commands for the
  user to run themselves, and points at `run_command_on_cluster` for short
  one-off checks instead.

## Known deviations from the IRI/PSI-J schemas

### ResourceSpec — resource types instead of nodes/cores (primary deviation)

TSUBAME4 sizes jobs by **resource type**, not the PSI/J `node_count`/
`process_count`/`cpu_cores_per_process` model (analogous to PBS's `-l
nodes=1:ppn=4`, which `hpc-agent-core`'s `PORTING.md` calls out by name as a
dialect that needs a full local `SchedulerBackend` subclass). Rather than a
core model edit (machines have no write access to `hpc_agent_core.models`),
these are mapped onto core's existing, machine-agnostic fields:

| TSUBAME concept | Carried via |
|---|---|
| `resource_type` (`node_f`/`node_h`/`node_q`/`node_o`/`gpu_1`/`gpu_h`/`cpu_160`…`cpu_4`, → `-l <type>=N`) | `attributes.custom_attributes["resource_type"]` |
| `resource_count` (the `=N`) | `resources.node_count` |
| `processes_per_node` (MPI ranks per unit — launch line only, not a scheduler flag) | `resources.processes_per_node` — core field, unchanged |
| `cpu_cores_per_process` (OpenMP threads per rank → `OMP_NUM_THREADS`) | `resources.cpu_cores_per_process` — core field, unchanged |
| `gpu_compute_mode` (→ `#$ -v GPU_COMPUTE_MODE`) | `attributes.custom_attributes["gpu_compute_mode"]` |

The PSI/J `gpus`/`memory`/`exclusive_node_use` fields are intentionally
unused: cores, memory, and GPUs are all fixed by the chosen resource type,
and there is no separate memory or exclusivity request.

### JobAttributes

- `account` holds the **TSUBAME group** (`qsub -g`), billed in points; core's
  generic tri-state semantics (`None`/`""`/`"<value>"`) already match
  TSUBAME's fallback/trial-run/explicit-group behavior exactly, with no
  TSUBAME-specific code needed.
- `priority` (`-5`/`-4`/`-3` → `-p`), `hold_jid` (`-hold_jid`), and `array`
  (`-t`) are carried via `custom_attributes` (see above); `reservation_id`
  (`-ar`) and `queue_name` (`-q`, e.g. `prior`) map directly onto core's
  existing fields of the same name.

### JobState

Native states map from Grid Engine `qstat` codes (`r`/`qw`/`h`/`t`/`s`/`S`/
`T`/`d`/`E`, and combinations, plus a substring-based fallback for any
unlisted combination) via a **local** `_map_ge_state()` in `compute.py` —
deliberately *not* `hpc_agent_core.models.map_ge_state`, which is a
stricter dict-only lookup with no fallback, covering only the subset of
codes cell2026's AGE deployment has actually produced. TSUBAME4's own
pre-migration table is richer (`hRwq`, `Rq`, plain `h`/`T`/`d`/`E`, plus the
fallback), and using core's version verbatim would silently misreport real
states as `unknown` — caught and fixed during this migration, see AGENTS.md's
validation-status section. `qacct` (`failed`/`exit_status`) for finished
jobs is handled by a separate local `_final_state()` helper — not the same
thing `_map_ge_state()` covers, since qacct has no state letter at all, so
it stays local rather than being forced through the same function.
Normalized values are lowercase (`queued`/`active`/`completed`/`failed`/
`canceled`/`held`/`unknown`), matching the IRI spec.

### submit_job return value

Returns `{job_id, script_path, group}` (group is `None` for a trial run)
rather than IRI's async `TaskSubmitResponse`, because SSH execution is
synchronous — `qsub` completes before we return. Intentional deviation.

### resource_id

Accepted and validated in all compute/status tools, but there is a single
resource: `tsubame4`.
