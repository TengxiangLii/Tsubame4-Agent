---
name: tsubame-submitting-jobs
description: Use when the user wants to run, submit, or launch a job (training, simulation, benchmark, GPU/MPI/OpenMP program) on TSUBAME4.0. Covers resource-type selection, JobSpec construction, TSUBAME groups/points, submission, and interactive sessions.
---

# Submitting jobs on TSUBAME4.0

TSUBAME4 is a GPU-first system: every node has 4× NVIDIA H100. Jobs are sized by
**resource type** (a fixed slice of a node), not by nodes/cores.

## Workflow

1. **Pick the resource type** — `get_facility` has the full table. Rules of thumb:
   - Full-node / multi-GPU / MPI+GPU → `node_f` (default; 192 cores + 4 H100).
   - Single-GPU job with modest CPU → `gpu_1` (8 cores + 1 H100).
   - Half / quarter node → `node_h` (2 GPU) / `node_q` (1 GPU).
   - CPU-only work → `cpu_4` … `cpu_160` (no GPU).
   Request several units with `resource_count` (e.g. `node_f` ×2). One job uses
   one resource type — they cannot be mixed.
2. **Set the group** — jobs are billed in TSUBAME points via `attributes.account`
   (the `-g` group). If omitted, the configured default is used; if there is no
   default either, the job submits as a **free trial run** (≤2 units, 3 min).
   Check points with `t4-user-info group point -g <group>` (via
   `run_command_on_cluster`); jobs stop starting when the balance runs out.
3. **Stage any needed files** with `fs_upload` / `fs_mkdir` (paths are relative to
   the home directory unless absolute).
4. **Submit with a JobSpec** via `submit_job`. Show the user the spec (or describe
   it) before submitting unless they asked to just run it. Load software in
   `pre_launch`; set the MPI launcher in `launcher`. Examples:

   Single-GPU job (`gpu_1`):
   ```json
   {
     "name": "train",
     "executable": "python train.py",
     "directory": "/home/2/ux00000/work",
     "pre_launch": "module purge && module load cuda",
     "resources": {"resource_type": "gpu_1", "resource_count": 1},
     "attributes": {"duration": "1:00:00", "account": "your-group"}
   }
   ```

   Multi-node MPI+GPU on 4 full nodes (Intel MPI, 8 ranks/node = 32 total):
   ```json
   {
     "name": "flatmpi",
     "executable": "./a.out",
     "launcher": "mpiexec.hydra -ppn 8 -n 32",
     "pre_launch": "module purge && module load cuda intel intel-mpi",
     "resources": {"resource_type": "node_f", "resource_count": 4, "processes_per_node": 8},
     "attributes": {"duration": "1:00:00", "account": "your-group"}
   }
   ```

   Hybrid MPI+OpenMP (OpenMPI, 1 rank/node × 192 threads):
   ```json
   {
     "name": "hybrid",
     "executable": "./a.out",
     "launcher": "mpirun -npernode 1 -n 4 -x LD_LIBRARY_PATH",
     "pre_launch": "module purge && module load openmpi/5.0.7-intel",
     "resources": {"resource_type": "node_f", "resource_count": 4, "processes_per_node": 1, "cpu_cores_per_process": 192},
     "attributes": {"duration": "1:00:00", "account": "your-group"}
   }
   ```
   The rendered Grid Engine script is kept on the cluster under `~/.tsubame/jobs/`
   — `fs_view` it if the user wants to inspect what was submitted.
5. **Verify**: `get_job_status` right after submission. Output lands in
   `<name>.o<job_id>` (stdout) and `<name>.e<job_id>` (stderr) in the submit dir.

## TSUBAME4 conventions

- **GPU-first, H100.** Load `cuda` (and/or `nvhpc`) for GPU code. `intel` gives
  the Intel compilers + MKL + Intel MPI; EPYC (Zen4) supports `-xCORE-AVX512`.
- **`module purge` before `module load`** in the script (the agent puts loads in
  `pre_launch`). `LD_LIBRARY_PATH`/`LD_PRELOAD` are **not** forwarded by `-V` —
  set them in the script.
- **Threads**: the agent sets `OMP_NUM_THREADS` from `cpu_cores_per_process`; you
  can override via `environment`.
- **Wall time** (`duration` → `h_rt`): default 1h, **max 24h**. Format `HH:MM:SS`.
- **Priority** (`attributes.priority`): -5 standard (default), -4/-3 higher but
  cost more points.
- **GPU compute mode**: set `resources.gpu_compute_mode` (0/1/2) on
  node_f/node_h/node_q/gpu_1 when a job needs EXCLUSIVE_PROCESS mode.
- **Containers**: set `container.image` (Apptainer .sif or `docker://…`); `/gs`,
  `/apps`, `/home` are bind-mounted and `--nv` is added for GPU resource types.
- **Trial run**: leave the group unset to test that a program launches for free
  (≤2 units, 3 min).
- **Outbound network** from compute nodes may need the site proxy — check the
  guide / portal for the current setting.
- **Interactive**: `qrsh -g <group> -l <type>=1 -l h_rt=… /bin/bash` (Normal
  queue) or `iqrsh` (shared interactive queue). Use `run_command_on_cluster` only
  for short non-interactive checks; prefer batch jobs.

## Don't

- Don't run computation on the login nodes — submit a job.
- Don't mix resource types in one job.
- Don't guess TSUBAME4-specific details — use `search_docs` from the tsubame-docs
  server.
- Don't `cancel_job` without confirming with the user.
