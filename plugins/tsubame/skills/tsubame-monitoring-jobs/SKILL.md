---
name: tsubame-monitoring-jobs
description: Use when the user asks about the status, progress, output, history, or failure of jobs on TSUBAME4.0, or about queue availability and TSUBAME points.
---

# Monitoring jobs on TSUBAME4.0

## Status checks

- **One job**: `get_job_status` — `state` is normalized (QUEUED/ACTIVE/COMPLETED/
  FAILED/CANCELED); `native_state` is Grid Engine's. For live jobs that is the
  `qstat` code (`r` running, `qw` queued, `h` hold, `t` transferring, `s`/`S`/`T`
  suspended, `d` deleting, `E` error); once a job finishes it leaves `qstat` and
  the state comes from `qacct` (exit status + `failed`).
- **My live jobs**: `get_job_statuses` with an empty list returns the current
  user's queued + running jobs. For a finished job, pass its ID (it falls back to
  `qacct`).
- **Cluster availability**: `get_resources` — per-queue used/reserved/available/
  total slots from `qstat -g c`, plus the static resource-type table.
- **TSUBAME points**: `get_project_allocations("<group>")` or
  `run_command_on_cluster("t4-user-info group point -g <group>")` — jobs stop
  starting once a group's balance is exhausted.

## Job output and failure triage

1. Stdout is `<name>.o<job_id>` and stderr `<name>.e<job_id>` in the directory the
   job ran in. Read with `fs_tail` (or `fs_head`/`fs_view`).
2. Common TSUBAME4 failure modes:
   - **Out of points / no group** → job rejected or never starts; check
     `t4-user-info group point -g <group>` and that a group is set.
   - **Wrong resource type** → too little memory for the workload, or a `cpu_*`
     type for GPU code (no GPU visible); move to `node_f`/`gpu_1`.
   - **Wall time exceeded** → `h_rt` too small (max 24h); raise `duration`.
   - **Threads unset** → performance collapse when `OMP_NUM_THREADS` wasn't set;
     check the script and the cores-per-process pairing.
   - **Module problems** → GPU code without `module load cuda`, or a stale env
     under `-V`; ensure `module purge` precedes `module load`.
3. The exact script that was submitted is kept in `~/.tsubame/jobs/` — `fs_view`
   it when debugging.

## Live job inspection

For an ACTIVE job, `run_command_on_cluster("qstat -j <id>")` shows the detailed
record (assigned queue/host, resource request, usage). For a GPU job you can
check utilization on its node via an interactive `qrsh` session or the job's own
`nvidia-smi` output if the script logs it.
