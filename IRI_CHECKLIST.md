# IRI Facility API coverage checklist

Tracks how far `tsubame-hpc` covers the [IRI Facility API](https://api.alcf.anl.gov/)
(ALCF implementation, spec at api.alcf.anl.gov/openapi.json — not committed; fetch
it when needed, see AGENTS.md). Each IRI endpoint maps to an MCP tool executed on a
TSUBAME4 login node over SSH via remotemanager — there is no REST service; we
emulate the API's shape and semantics.

**The ✅/🔜/❌ verdicts below are specific to TSUBAME4.** They were re-decided against
what TSUBAME4 can actually do, not inherited from the machine this plugin was
ported from (HOKUSAI BigWaterfall2, Slurm). The clearest difference: the
**allocation endpoints are implemented here** — TSUBAME4 exposes a per-group
TSUBAME-points budget via `t4-user-info group point` — whereas the GPU-first
reference port (AI4S) deferred them for lack of accounting. When porting onward,
re-decide every row from scratch.

Legend: ✅ implemented · 🔜 planned next · ❌ deferred (with reason)

## facility

| IRI endpoint | Tool | Status | Notes |
|---|---|---|---|
| GET /facility | `get_facility` | ✅ | Static data from `data/tsubame_config.json` |
| GET /facility/sites | — | ❌ | Single-site deployment; fold into `get_facility` if ever needed |
| GET /facility/sites/{site_id} | — | ❌ | Same |

## status

| IRI endpoint | Tool | Status | Notes |
|---|---|---|---|
| GET /status/resources | `get_resources` | ✅ | One resource (`tsubame4`); per-queue slot summary from `qstat -g c` + static resource types |
| GET /status/resources/{resource_id} | `get_resource` | ✅ | Same detail for the single resource |
| GET /status/incidents | — | ❌ | No machine-readable incident/maintenance feed exposed on the login node; users check the portal |
| GET /status/incidents/{id} | — | ❌ | Same |
| GET /status/events | — | ❌ | Same |
| GET /status/events/{id} | — | ❌ | Same |

## account

| IRI endpoint | Tool | Status | Notes |
|---|---|---|---|
| GET /account/capabilities | — | ❌ | No equivalent concept exposed on TSUBAME4 |
| GET /account/projects | `get_projects` | ✅ | TSUBAME groups from `id -Gn` (each usable as `qsub -g`) |
| GET /account/projects/{id} | `get_project` | ✅ | Group detail incl. point balance |
| GET .../project_allocations | `get_project_allocations` | ✅ | **Re-decided for TSUBAME4 (was ❌ on AI4S).** `t4-user-info group point -g <group>` → deposit + remaining TSUBAME points |
| GET .../project_allocations/{id} | `get_project_allocations` | ✅ | Same source, single group |
| GET .../user_allocations | `get_user_allocations` | ✅ | Point balance for each of the user's groups |
| GET .../user_allocations/{id} | `get_project_allocations` | ✅ | Per-group point balance |

## compute

| IRI endpoint | Tool | Status | Notes |
|---|---|---|---|
| POST /compute/job/{resource_id} | `submit_job` | ✅ | JobSpec → Grid Engine script (kept in `~/.tsubame/jobs/`); `qsub -g`; returns `{job_id, script_path, group}` — see deviation note |
| PUT /compute/job/{rid}/{job_id} | `update_job` | ✅ | `qalter`; time_limit/name/priority/hold_jid, mostly queued-only |
| GET /compute/status/{rid}/{job_id} | `get_job_status` | ✅ | `qstat` (live) with `qacct` fallback for finished jobs |
| POST /compute/status/{rid} | `get_job_statuses` | ✅ | Batch; empty list = current user's live (queued + running) jobs |
| DELETE /compute/cancel/{rid}/{job_id} | `cancel_job` | ✅ | `qdel` + post-cancel state report |

## filesystem

| IRI endpoint | Tool | Status | Notes |
|---|---|---|---|
| GET /filesystem/ls | `fs_ls` | ✅ | |
| GET /filesystem/stat | `fs_stat` | ✅ | |
| GET /filesystem/view | `fs_view` | ✅ | 200KB cap; text only |
| GET /filesystem/head | `fs_head` | ✅ | |
| GET /filesystem/tail | `fs_tail` | ✅ | Primary way to read job output (`<name>.o<id>`) |
| POST /filesystem/mkdir | `fs_mkdir` | ✅ | |
| POST /filesystem/upload | `fs_upload` | ✅ | Text or base64 binary via MCP; 5 MB cap |
| GET /filesystem/download | `fs_download` | ✅ | Base64; 5 MB cap; suggests scp for larger files |
| GET /filesystem/checksum | `fs_checksum` | ✅ | `sha256sum` |
| POST /filesystem/mv | `fs_mv` | ✅ | destructive (documented) |
| POST /filesystem/cp | `fs_cp` | ✅ | `cp -r` |
| DELETE /filesystem/rm | — | ❌ | Deliberately omitted (destructive); use the escape hatch with user confirmation |
| PUT /filesystem/chmod | `fs_chmod` | ✅ | |
| PUT /filesystem/chown | `fs_chown` | ✅ | group-only changes work for normal users |
| POST /filesystem/symlink | `fs_symlink` | ✅ | `ln -s` |
| POST /filesystem/compress | `fs_compress` | ✅ | `tar` gzip/bzip2/xz/none + match_pattern |
| POST /filesystem/extract | `fs_extract` | ✅ | `tar -x` |

## task

| IRI endpoint | Tool | Status | Notes |
|---|---|---|---|
| GET /task/{task_id} | — | ❌ | Our SSH execution is synchronous — `submit_job` returns `job_id` directly (see deviation) |
| DELETE /task/{task_id} | — | ❌ | Same |
| GET /task | — | ❌ | Same |

## extensions (no IRI counterpart)

| Tool | Notes |
|---|---|
| `run_command_on_cluster` | Arbitrary login-shell command (e.g. `module avail`, `t4-user-info`, `qstat`). Marked as a non-IRI escape hatch. |

---

## Known deviations from the IRI/PSI-J schemas

### ResourceSpec — resource types instead of nodes/cores (primary deviation)

TSUBAME4 sizes jobs by **resource type**, not the PSI/J `node_count` /
`process_count` / `cpu_cores_per_process` model (this is analogous to the PBS
`-l nodes=1:ppn=4` case the porting guide calls out). So `ResourceSpec` carries:

| Field | Meaning |
|---|---|
| `resource_type` | `node_f`/`node_h`/`node_q`/`node_o`/`gpu_1`/`gpu_h`/`cpu_160`…`cpu_4` (→ `-l <type>=N`) |
| `resource_count` | number of units (the `=N`) |
| `processes_per_node` | MPI ranks per unit — used for the launch line, **not** a scheduler flag |
| `cpu_cores_per_process` | OpenMP threads per rank — sets `OMP_NUM_THREADS` |
| `gpu_compute_mode` | TSUBAME4 extension → `#$ -v GPU_COMPUTE_MODE` |

The PSI/J `node_count`, `memory`, and `gpus` fields are intentionally absent:
cores, memory, and GPUs are all fixed by the chosen resource type.

### JobAttributes

- `account` holds the **TSUBAME group** (`qsub -g`), billed in points; falls back
  to the config default, else a free trial run.
- `priority` (−5/−4/−3 → `-p`), `reservation_id` (`-ar`), `hold_jid`
  (`-hold_jid`), `array` (`-t`), and optional `queue_name` (`-q`, e.g. `prior`)
  are Grid Engine attributes.

### JobState

Native states map from Grid Engine `qstat` codes (`r`/`qw`/`h`/`t`/`s`/`S`/`T`/
`d`/`E`, and combinations) via `map_ge_state`, and from `qacct`
(`failed`/`exit_status`) for finished jobs via `map_ge_final_state`. Normalized
values are uppercase (`QUEUED`/`ACTIVE`/`COMPLETED`/`FAILED`/`CANCELED`/`HELD`/
`UNKNOWN`).

### submit_job return value

Returns `{job_id, script_path, group}` (group is `None` for a trial run) rather
than IRI's async `TaskSubmitResponse`, because SSH execution is synchronous —
`qsub` completes before we return. Intentional deviation.

### resource_id

Accepted and validated in all compute/status tools, but there is a single
resource: `tsubame4`.
