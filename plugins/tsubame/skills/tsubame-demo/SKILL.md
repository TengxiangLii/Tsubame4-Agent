---
name: tsubame-demo
description: Interactive demo of Tsubame4Agent — walks through facility info, live cluster status, docs search, filesystem access, and a free GPU trial-run job on TSUBAME4.0.
user-invocable: true
---

# Tsubame4Agent demo

Run each step in order. Present results as a readable narrative — not raw JSON
dumps. Use markdown headers and tables to make it scannable. Pause after each step
and show output before moving on.

---

## Step 1 — Facility overview

Call `get_facility`. Present the key facts as a short table:
- Node: CPU (AMD EPYC 9654 ×2), memory, **4× NVIDIA H100** per node
- Resource types: name → cores, memory, GPUs, local scratch (one row each)
- Storage tiers (home, work, group disks, local scratch)

Lead with one sentence: **"TSUBAME4.0 is Institute of Science Tokyo's GPU-first
supercomputer — 240 nodes, each with two 96-core AMD EPYC CPUs and four NVIDIA
H100 GPUs, scheduled with Altair Grid Engine."**

---

## Step 2 — Live cluster status

Call `get_resources`. Show the per-queue slot summary (used / available / total)
and point out where capacity is free right now — that's where a job starts
fastest.

---

## Step 3 — Documentation search

Call `search_docs` with *"how are jobs sized and billed — resource types and
TSUBAME points?"*

This surfaces something genuinely TSUBAME4-specific: the resource-type model and
the points budget that govern every submission — not something you can guess from
generic HPC knowledge.

Show the top result: the breadcrumb, a short excerpt, and the source. The result
will note `[search_method: bm25]` — say: *"Running on BM25 keyword search, which
ships with the plugin and works fully offline."*

---

## Step 4 — Filesystem

Call `fs_ls(".")` to list the user's home directory. Show it cleanly (names,
sizes, dates). Then demonstrate the toolkit:
1. `fs_upload("/tmp/tsubame-demo.txt", "hello from Tsubame4Agent\n")` — write a file
2. `fs_checksum("/tmp/tsubame-demo.txt")` — show the SHA-256
3. `fs_cp(...)` then `fs_checksum` on the copy — confirm the checksum matches

Present this as: *"Upload, checksum, copy — the filesystem toolkit."*

---

## Step 5 — Recent jobs

Call `get_job_statuses([])` (empty list = current live jobs). If there are jobs,
show them as a table: job ID | name | state | queue | slots. If none, say so and
move to Step 6.

---

## Step 6 — Free trial-run test job

Tell the user: *"Let's submit a free **trial run** to verify end-to-end
submission — no TSUBAME group, no points charged."* A trial run is submitted with
no `-g`, so set `account` to an **empty string** `""` (this forces a trial run
even when a default group is configured), and keep it within the trial limits
(≤2 units, ≤3 min).

Submit via `submit_job` with this spec:
```json
{
  "name": "tsubame-demo",
  "executable": "hostname && echo '---' && nvidia-smi -L && echo '---' && nproc",
  "resources": {"resource_type": "node_f", "resource_count": 1},
  "attributes": {"duration": "0:03:00", "account": ""}
}
```

Show the rendered job ID and script path (note there is no `-g`, so it is a trial
run). Then call `get_job_status(<job_id>)` immediately and report the initial
state.

---

## Step 7 — Monitor and read output

Poll `get_job_status` every ~15 seconds (use `run_command_on_cluster("sleep 15")`
to wait). Stop when the state is `completed` or `failed` (or after ~5 polls — tell
the user to check back with `get_job_status` if it is still queued).

Once completed, read the output file `tsubame-demo.o<job_id>` with `fs_tail` and
show it. It should list the node hostname and **four NVIDIA H100 GPUs** — confirm
that matches what `get_facility` reported.

---

## Closing

Summarize in 5 bullets:
- Facility and live cluster status checked
- Documentation searched (resource types + points)
- Filesystem explored with upload, checksum, and copy
- A free trial-run job submitted, ran, and its output (4× H100 node) retrieved
- Everything went through one SSH layer to a TSUBAME4 login node

Then say: *"From here you can submit real workloads with /tsubame-submitting-jobs,
monitor them with /tsubame-monitoring-jobs, or ask anything about the cluster."*
