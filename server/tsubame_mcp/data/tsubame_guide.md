# TSUBAME4.0

An original, plain-language orientation to the TSUBAME4.0 system at Institute of
Science Tokyo, written for users who drive it through Tsubame4Agent. It records
the site-specific facts that shape how you ask for work — not general HPC/Linux
background, and not a command reference. Stable facts (resource-type shapes,
paths, conventions) are stated here so the agent can size a job without a
round-trip; genuinely changing values (queue occupancy, your point balance,
exact installed versions) are left to the live system, which the agent queries
on demand.

## What TSUBAME4 is

TSUBAME4 is a GPU-first supercomputer scheduled with Altair Grid Engine and
reached through shared login nodes. It is 240 identical nodes, and every node
carries **four NVIDIA H100 GPUs** alongside two 96-core AMD EPYC (Genoa) CPUs and
768 GiB of memory. There is no separate "CPU cluster" and "GPU cluster": the same
GPU-equipped nodes are logically sliced into the resource types you request.

The practical consequence for working with the agent: think in whole GPU nodes
first. The default job takes a full node (`node_f`, 192 cores + 4 H100); ask for
a smaller slice or a CPU-only slice only when a workload genuinely needs less.

## Getting on the system

You connect over SSH to `login.t4.gsic.titech.ac.jp`, load-balanced across the
login nodes. Authentication is by SSH key only — no passwords — so register your
public key through the web portal before your first login. Login nodes are shared
and strictly for editing, building, staging files, and submitting: anything that
runs in parallel, uses real memory, or lasts more than a few minutes belongs in a
job. Have the agent submit it rather than running it on the front end.

## Sizing a job: resource types

This is the central TSUBAME4 idea and where it differs most from other clusters.
You do not ask for "N nodes and M cores"; you ask for a number of **resource-type
units**, and each type is a fixed slice of a node:

| resource type | CPU cores | memory | GPUs | for |
|---|---|---|---|---|
| `node_f` (default) | 192 | 768 GB | 4 | full-node and multi-GPU / MPI+GPU work |
| `node_h` | 96 | 384 GB | 2 | half a node |
| `node_q` | 48 | 192 GB | 1 | a quarter node |
| `node_o` | 24 | 96 GB | ½ (MIG) | an eighth node |
| `gpu_1` | 8 | 96 GB | 1 | a single-GPU job with modest CPU |
| `gpu_h` | 4 | 48 GB | ½ (MIG) | a fractional-GPU job |
| `cpu_4` … `cpu_160` | 4 … 160 | proportional | 0 | CPU-only work |

You request, for example, two full nodes as `node_f=2`. A job uses one resource
type only — you cannot mix `node_f` and `gpu_1` in a single job. Every job also
needs a maximum run time (`h_rt`), which caps at 24 hours. The agent turns your
description into the right `-l` request.

## Groups, points, and the trial run

Compute is billed in **TSUBAME points** to a *group*, named at submission with
`-g <group>`. The agent can hold a default group and let you override it per job.
Each group has a point balance that jobs draw down as they run; when it is
exhausted the group's jobs stop starting. The balance changes continuously — ask
the agent to read it live (`t4-user-info group point`) rather than assuming it.
Higher priority (`-3`/`-4` instead of the default `-5`) spends points faster.

There is one important free path: a **trial run**. Submit with *no* group and the
job runs without charge, limited to 2 resource-type units, 3 minutes, and lowest
priority. It is meant for checking that a program launches — not for real
science — and it is what the agent uses for a smoke test.

## Software, compilers, and MPI

Software is provided through environment modules. Because versions change, have
the agent list what is installed live rather than relying on a frozen list — but
a few stable conventions matter when building and launching:

- **GPU work loads CUDA.** `module load cuda` (and/or the `nvhpc` NVIDIA HPC SDK)
  provides the GPU toolchain; build and run with the same modules.
- **Intel oneAPI is the primary CPU toolchain.** Loading `intel` brings the Intel
  compilers, MKL, and Intel MPI together; the EPYC (Zen4) cores support AVX-512.
- **Launch MPI with the matching launcher.** Intel MPI uses
  `mpiexec.hydra -ppn <ranks-per-node> -n <total>`; Open MPI
  (`module load openmpi/5.0.7-intel`) uses
  `mpirun -npernode <ranks-per-node> -n <total> -x LD_LIBRARY_PATH`. The assigned
  node list is in `$PE_HOSTFILE`.
- **Threaded code must be told its thread count** (`OMP_NUM_THREADS`), matched to
  the cores per process, or it runs with the wrong number and far slower.
- **`module purge` before `module load`** in a job that inherits the environment
  (`-V`), and remember that `LD_LIBRARY_PATH`/`LD_PRELOAD` are *not* forwarded —
  set them inside the script.

Major preinstalled applications include Gaussian, VASP, AMBER, ANSYS, ABAQUS,
COMSOL, Schrodinger, MATLAB, and Materials Studio — confirm availability and
version live, since the catalogue evolves.

## Storage

Several places to keep data, each with a purpose:

- `/home/<group>/<user>` — code, scripts, small files; a tight ~25 GiB quota.
- `/work/<group>/<user>` — your everyday work area, ~100 GiB, no application
  needed; it is your home path with `home` replaced by `work`.
- `/gs/fs` and `/gs/bs` — group disks (high-speed SSD and large-scale HDD Lustre)
  purchased per group for shared datasets and results.
- `/local` — node-local NVMe scratch that exists only for a job's duration; stage
  inputs onto it for I/O-heavy stages and copy results back out before the job
  ends, because it is wiped when the job releases the node.

The agent can report your current usage and quota (`t4-user-info disk …`) on
request.

## Containers

Apptainer (Singularity) is available when you want to carry a specific software
stack onto the machine. Pull a ready-made image or build your own, then have the
agent run your program inside it; site storage (`/gs`, `/apps`, `/home`) is
bind-mounted and, for a GPU resource type, container GPU access (`--nv`) is
enabled automatically.

## Running work through the agent

You describe a job in resource terms — which resource type and how many units,
how long, which group to charge, and (for parallel work) the MPI ranks and
threads — and the agent assembles and submits the Grid Engine job, then returns a
job ID to track. You do not write `#$` job scripts or recall scheduler flags
yourself. Most jobs are single- or multi-GPU; MPI+GPU across several `node_f`
units is common for large runs.

## Following jobs and untangling failures

After submission, a job's queue position and state come from `qstat`; once it
finishes it leaves `qstat` and its record moves to `qacct` (which the agent reads
for exit status and timing). A job's console output is written next to where it
was launched, as `<jobname>.o<jobid>` (standard output) and `<jobname>.e<jobid>`
(standard error) — the agent can read and summarize these.

When a job misbehaves, the cause is usually one of a few:

- The group ran out of TSUBAME points, or no group was named.
- The requested resource type was wrong for the workload (too little memory, or a
  CPU-only type for GPU code).
- It hit its `h_rt` wall-time limit.
- `OMP_NUM_THREADS` was left unset, so threaded performance collapsed.
- The wrong modules were loaded, or GPU code ran without `module load cuda`.

The agent can inspect the failed job's record and output to point at which it was.

## Staying current

TSUBAME4 evolves — installed software, limits, and policies change. The
authoritative sources are the portal (https://www.t4.cii.isct.ac.jp/en/) and the
live state of the machine, which the agent can query whenever a precise, current
answer matters. For anything not covered here — especially accounts, points, and
policy — fall back to those or to TSUBAME support.
