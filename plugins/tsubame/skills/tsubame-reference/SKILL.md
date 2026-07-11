---
name: tsubame-reference
description: Use when answering any question about TSUBAME4.0 specifics — login, groups/points, resource types, modules, storage, policies — or when unsure about a cluster detail. Search the built-in guide or check live state instead of guessing.
---

# TSUBAME4 documentation reference

Do not answer TSUBAME4-specific questions from memory — ground answers in the
built-in guide, and prefer live state for anything that changes over time.

## Workflow

1. `search_docs` (tsubame-docs server) with the user's question. Results carry
   no URL — this searches a guide bundled with the agent, not a live site —
   don't invent or guess one to cite.
2. If results look incomplete, `list_doc_sections` shows the full table of
   contents; `read_doc_section` reads a section in full by its breadcrumb.
3. For anything current or precise — installed software, queue occupancy, your
   point balance, disk usage — **check live state**, since the guide deliberately
   doesn't freeze these:
   - `get_facility` / `get_resources` (tsubame-hpc) for resource types and queue
     load.
   - `run_command_on_cluster` for `module avail` (software), `t4-user-info group
     point -g <group>` (points), `t4-user-info disk home` (quota).
4. If still uncovered, point the user to the TSUBAME Portal
   (https://www.t4.cii.isct.ac.jp/en/) for accounts, points, and policy.

## Orientation (stable facts)

- **GPU-first machine.** 240 nodes, each 2× AMD EPYC 9654 (192 cores) + **4×
  NVIDIA H100** + 768 GiB. Think GPU first; the default job takes a full node.
- **Resource types**, not nodes/cores: `-l <type>=<N>`. `node_f` (full, 4 GPU),
  `node_h`/`node_q`/`node_o` (fractions), `gpu_1`/`gpu_h` (single/fractional GPU),
  `cpu_4`…`cpu_160` (CPU-only). Max wall time 24h. One type per job.
- **Groups & points**: jobs are billed in TSUBAME points to a group (`-g`).
  Balance is finite and read live. Trial runs (no `-g`) are free but tiny.
- **Scheduler**: Altair Grid Engine — `qsub` (batch), `qrsh`/`iqrsh`
  (interactive), `qstat`, `qacct` (finished jobs), `qdel`. Output in
  `<name>.o<id>` / `<name>.e<id>`.
- **Modules**: `module avail/load/purge`. `cuda`/`nvhpc` for GPU, `intel` for
  Intel oneAPI + MKL + Intel MPI, `openmpi/5.0.7-*` for Open MPI.
- **Storage**: `/home` (25 GiB), `/work` (100 GiB, `${HOME/home/work}`), `/gs/fs`
  & `/gs/bs` (group disks), `/local` (per-job node-local NVMe). Lustre.
- **Login**: `login.t4.gsic.titech.ac.jp` (round-robin); key-based SSH, keys
  registered on the portal.

## Keeping the guide fresh

The docs index is built from `server/tsubame_mcp/data/tsubame_guide.md` (an
original guide, not the vendor manual). To revise it, edit that file and rebuild:
`python -m tsubame_mcp.ingest --no-embed` (BM25 index). No embedding endpoint
ships for TSUBAME4, so search always uses BM25 keyword matching.
