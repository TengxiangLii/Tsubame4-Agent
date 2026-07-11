# Tsubame4Agent — User Guide

This is the complete guide to using **Tsubame4Agent**, a plugin that lets you
operate the **TSUBAME4.0** supercomputer (Institute of Science Tokyo) by talking
to an AI agent in ordinary language.

It's written for people who may be new to **both** supercomputers **and** AI
agents. You do not need to know Linux commands or job schedulers to use this.

**Contents**

1. [Understanding the agent workflow](#1-understanding-the-agent-workflow)
2. [TSUBAME4 in five minutes](#2-tsubame4-in-five-minutes)
3. [What you can do with the agent](#3-what-you-can-do-with-the-agent)
4. [Worked examples](#4-worked-examples)
5. [Everyday recipes (cheat-sheet)](#5-everyday-recipes-cheat-sheet)
6. [Troubleshooting & FAQ](#6-troubleshooting--faq)
7. [Reference appendix](#7-reference-appendix)

If you haven't installed and connected the plugin yet, do the
[Quickstart](../QUICKSTART.md) first (about 5 minutes).

---

## 1. Understanding the agent workflow

### What "the agent" is

You already use an AI assistant (Claude Code or Codex). **Tsubame4Agent adds a
set of abilities to it** so it can reach out and operate the TSUBAME4
supercomputer on your behalf. You type requests in plain English; the agent
figures out the right actions and carries them out.

Think of it as a knowledgeable lab assistant who *does* know all the cluster
commands, sitting between you and the machine:

- **You say** what you want ("run this on a GPU for two hours").
- **The agent** translates that into the correct cluster operations, runs them
  over your SSH connection, and reports back in plain language.

### The old way vs. the agent way

Traditionally, using a supercomputer looks like this:

```
ssh you@login.t4.gsic.titech.ac.jp        # log in
nano job.sh                                # write a script full of #$ directives
qsub -g mygroup job.sh                     # submit it to the scheduler
qstat                                      # check if it's running (cryptic table)
cat job.sh.o8048242                        # find and read the output file
```

With the agent, the same thing is:

> **Run `train.py` on one GPU for two hours and tell me when it finishes.**

The agent writes the job script, submits it, watches it, and shows you the
output. You never memorize a flag.

### What the agent does for you vs. asks you

- It acts **using your SSH key** — the same access you'd have yourself. It cannot
  do anything on the cluster you couldn't do.
- It will usually **show you its plan** (what job it's about to submit) before
  acting.
- It **asks for confirmation before anything that spends money or deletes data** —
  submitting a real (billed) job, cancelling a job, deleting or overwriting files.
- **Looking is free.** Checking the queue, your points, or your files costs
  nothing and doesn't touch your compute budget.

### Skills and slash commands

The plugin ships with a few **skills** — pre-written playbooks the agent follows
for common workflows. You can trigger them explicitly by typing a slash command:

| Command | What it's for |
|---|---|
| `/tsubame-demo` | A guided end-to-end tour that runs a free test job. |
| *(the others fire automatically)* | setup, submitting, monitoring, and looking up docs |

**You rarely need to type these.** Plain English triggers the right skill on its
own — *"help me submit a job"* activates the submitting-jobs skill; *"why did my
job fail?"* activates the monitoring skill. The slash commands are just a
shortcut when you want to be explicit.

### A note on trust and safety

- Read-only questions (status, points, file listings, doc searches) are safe and
  free — ask freely.
- Submitting a **real** job spends TSUBAME points; the agent confirms first.
- You can always say *"cancel that job"* — the agent stops it.
- The agent works only within your account and your SSH access.

---

## 2. TSUBAME4 in five minutes

Just enough background so the examples make sense.

### Login node vs. compute node

When you connect to TSUBAME4 you land on a **login node** — a shared front desk
for editing files and submitting work. **You never run heavy computation there**
(it's shared by everyone and would slow the system for all). Instead you submit a
**job**, which runs on a dedicated **compute node**. The agent always does this
correctly for you.

### What a "job" is

A **job** is a piece of work you hand to the **scheduler** (TSUBAME4 uses one
called Altair Grid Engine). The scheduler puts your job in a **queue**, waits
until the resources you asked for are free, runs it, and saves the output to
files. You get a **job ID** (a number like `8048242`) to track it.

### Resource types — "t-shirt sizes" for jobs

Here's the one TSUBAME4-specific idea worth learning. TSUBAME4 is a **GPU-first**
machine: it has 240 nodes, and **every node has four NVIDIA H100 GPUs**. You
don't ask for "N cores" — you ask for a **resource type**, which is a fixed slice
of a node (like choosing a t-shirt size). The common ones:

| Resource type | CPU cores | Memory | GPUs | Good for |
|---|---|---|---|---|
| `node_f` (default) | 192 | 768 GB | **4** | full-node / multi-GPU / big MPI jobs |
| `node_h` | 96 | 384 GB | 2 | half a node |
| `node_q` | 48 | 192 GB | 1 | a quarter node |
| `gpu_1` | 8 | 96 GB | **1** | a single-GPU job (e.g. one training run) |
| `gpu_h` | 4 | 48 GB | ½ | a fractional GPU (small/interactive) |
| `cpu_4` … `cpu_160` | 4 … 160 | proportional | 0 | CPU-only work (no GPU) |

Two rules: **one job uses one resource type** (you can't mix), and you can request
several units of the same type (e.g. two full nodes). You don't have to memorize
this — say *"I need one GPU"* and the agent picks `gpu_1`; say *"a whole node"*
and it picks `node_f`. The full table is in the [appendix](#7-reference-appendix).

### Groups, TSUBAME points, and the free trial run

Compute time is billed in **TSUBAME points**, charged to a **group** (a project
account you belong to, e.g. `tga-imlabCASB2`). The agent remembers your default
group, so you don't specify it every time. When your group runs out of points,
its jobs stop starting — you can ask the agent to check the balance anytime.

There's one free path: a **trial run**. If a job is submitted **without a group**,
it runs for free, limited to a small size and 3 minutes. It's meant for testing
that something launches — perfect for following along in this guide without
spending anything.

### Where to keep your files

| Location | Size | Use it for |
|---|---|---|
| `/home/<group>/<you>` | 25 GiB | code, scripts, small files |
| `/work/<group>/<you>` | 100 GiB | your everyday working data |
| `/gs/fs`, `/gs/bs` | purchased per group | large shared datasets/results |
| `/local` | per-job | fast scratch that exists only while a job runs |

The agent can move files between your laptop and these locations, and tell you
your quota usage.

### Software: modules and containers

Software on TSUBAME4 is loaded with **modules** (e.g. `module load cuda` for GPU
code, `intel` for the Intel compilers). The agent adds the right `module load`
lines to your job for you. You can also bring your own software stack in an
**Apptainer container** (like Docker for HPC) — the agent runs your program
inside it and turns on GPU access automatically.

---

## 3. What you can do with the agent

Everything below is just a matter of *asking*. Grouped by kind of task:

**Explore the machine**
- *"Describe the TSUBAME4 cluster."* — hardware, resource types, storage.
- *"Is the cluster busy right now? Where would my job start fastest?"*

**Check your account**
- *"How many TSUBAME points does my group have left?"*
- *"Which groups can I charge jobs to?"*
- *"How much of my home/work disk quota am I using?"*

**Work with files**
- *"List my home directory."* / *"Show me the last 30 lines of results.log."*
- *"Upload this script to the cluster."* / *"Download that output file to my
  laptop."*
- *"Make a folder called experiments."* / *"Compress that results directory."*

**Submit jobs**
- *"Run `train.py` on one GPU for an hour."*
- *"Submit a 4-node MPI job using all the GPUs."*
- *"Run this inside an Ubuntu container with GPU access."*

**Monitor and debug**
- *"What are my jobs doing right now?"*
- *"Is job 8048242 done yet?"*
- *"My job failed — why? Show me the error."*
- *"Cancel job 8048242."* / *"Give job 8048242 another hour of runtime."*

**Look things up**
- *"How do I run Gaussian here?"* / *"What's the storage policy?"* — the agent
  searches TSUBAME4's built-in documentation and cites what it found.

**Anything else**
- For a task no built-in ability covers, the agent can run a specific command on
  the cluster for you (for example, listing available software with
  `module avail`). Just describe what you need.

---

## 4. Worked examples

Each example shows **what you say**, **what the agent does**, and **what you get
back**. Prompts are in quotes — type them in your own words; you don't have to
match them exactly.

### Example 1 — Is the cluster busy?

> **Is TSUBAME4 busy right now? Where would a GPU job start soonest?**

The agent checks the live queue load and reports how many slots are used vs.
free, then tells you which queue has capacity. Costs nothing.

### Example 2 — Check your points

> **How many TSUBAME points does my group have left?**

The agent looks up your group's balance and replies, e.g. *"Group
tga-imlabCASB2 has 148.82 points remaining."* Use this before a big job.

### Example 3 — Run a script on one GPU (a real, billed job)

> **Upload `train.py` from my current folder, then run it on one GPU for one
> hour. Load CUDA first.**

The agent will:
1. Upload `train.py` to the cluster.
2. Build a job asking for `gpu_1` (1 GPU), 1 hour, with `module load cuda`.
3. **Show you the plan and ask to confirm** (this spends points).
4. Submit it and give you the job ID.

Then follow up: *"Tell me when it's done and show the output."*

### Example 4 — A bigger multi-GPU MPI job

> **Run my program `./a.out` as an MPI job across 4 full nodes, 8 processes per
> node, for 2 hours. Use Intel MPI.**

The agent picks `node_f` × 4, writes the job script with `module load` and the
right `mpiexec.hydra -ppn 8 -n 32` launch line, and submits it after you confirm.
You didn't write a single scheduler directive.

### Example 5 — Diagnose a failed job

> **My job 8048242 failed. What went wrong?**

The agent reads the job's record and its output/error files, then explains in
plain language — for example *"it ran out of memory; try a larger resource type"*
or *"it hit its 1-hour time limit; ask for more time."* Common causes it can spot:
out of points, wrong resource type, wall-time exceeded, threads not set, or a
module conflict.

### Example 6 — Manage a running job

> **What are my jobs doing?** → agent lists them with states.
>
> **Cancel job 8048242.** → agent confirms, then stops it.
>
> **Actually, give job 8048242 another hour instead.** → agent extends its time
> limit.

### Example 7 — Look up how to use an application

> **How do I run Gaussian on TSUBAME4?**

The agent searches the built-in guide, summarizes the relevant section, and can
then help you build a job for it. Ask *"what software is installed?"* and it can
list available modules live.

### Example 8 — A completely free test run

> **Submit a free trial run that prints the node name and its GPUs.**

The agent submits a tiny job **with no group** (so it's free), waits ~30 seconds,
and shows you output listing four NVIDIA H100 GPUs. Great for confirming things
work without spending points. (This is exactly what `/tsubame-demo` does.)

---

## 5. Everyday recipes (cheat-sheet)

| Your goal | Say something like… |
|---|---|
| See the machine's specs | "Describe the TSUBAME4 cluster." |
| Check how busy it is | "How busy is the cluster right now?" |
| Check your budget | "How many points does my group have left?" |
| Check disk usage | "How much of my disk quota am I using?" |
| List files | "Show me my home directory." |
| Read a file / job output | "Show the last 40 lines of results.log." |
| Send a file to the cluster | "Upload run.sh to my work directory." |
| Get a file back | "Download output.tar.gz to my laptop." |
| Run on 1 GPU | "Run train.py on one GPU for 2 hours." |
| Run on a full node | "Run this on a whole node (4 GPUs) for 1 hour." |
| Run CPU-only | "Run this on 16 CPU cores, no GPU, for 30 minutes." |
| Free test | "Submit a free trial run of `hostname`." |
| Check a job | "Is job 8048242 done?" |
| List my jobs | "What are my jobs doing?" |
| Debug a failure | "Why did job 8048242 fail?" |
| Cancel | "Cancel job 8048242." |
| More time | "Give job 8048242 another hour." |
| Look something up | "How do I use containers here?" |

---

## 6. Troubleshooting & FAQ

**"The agent says it's not configured."**
Run setup: *"set up my TSUBAME connection."* It creates `~/.hpc-agent/tsubame.json`
with your SSH host and group. You can check that file exists and is correct.

**"Permission denied" or it's asking for a password.**
TSUBAME4 accepts **SSH keys only**. Your public key must be registered on the
[TSUBAME portal](https://www.t4.cii.isct.ac.jp/en/), and you should be able to
`ssh login.t4.gsic.titech.ac.jp` from your own terminal. The agent cannot answer
password prompts.

**My job was rejected or never starts.**
Usually your group is out of TSUBAME points, or no group is set. Ask *"how many
points does my group have?"* If you just want to test something, ask for a **free
trial run** instead.

**My job failed / ran badly.** Tell the agent *"why did job N fail?"* and it will
read the logs. Common fixes it will suggest:
- *Out of memory* → use a bigger resource type (e.g. `node_f`).
- *Time limit hit* → ask for more time (max 24 hours).
- *Slow / wrong thread count* → the agent sets `OMP_NUM_THREADS`; mention it's a
  threaded program.
- *Module conflict* → don't load conflicting MPI modules; the agent handles this.

**I saw something about "rsync version 2.6.9."**
Nothing to do — the plugin handles this automatically. (On macOS the system rsync
is old, but the agent only uses direct SSH, so it doesn't matter.)

**Does the agent spend my points just by looking around?**
No. Checking status, points, files, and docs is free. Only **submitting a real
job** (with your group) costs points, and the agent confirms before doing that.
Trial runs (no group) are always free.

**I use Codex, not Claude Code.**
Everything works the same — you talk to the agent in plain English. The only
differences are install (`codex plugin marketplace add TengxiangLii/Tsubame4-Agent`,
then install via `/plugins`) and that you invoke skills from the `/plugins`
menu. All the example prompts above apply unchanged.

---

## 7. Reference appendix

### Resource types (full table)

| Type | CPU cores | Memory (GB) | GPUs | Local scratch (GiB) |
|---|---|---|---|---|
| `node_f` *(default)* | 192 | 768 | 4 | 1660 |
| `node_h` | 96 | 384 | 2 | 830 |
| `node_q` | 48 | 192 | 1 | 415 |
| `node_o` | 24 | 96 | ½ (MIG) | 200 |
| `gpu_1` | 8 | 96 | 1 | 200 |
| `gpu_h` | 4 | 48 | ½ (MIG) | 100 |
| `cpu_160` | 160 | 368 | 0 | 830 |
| `cpu_80` | 80 | 184 | 0 | 415 |
| `cpu_40` | 40 | 92 | 0 | 200 |
| `cpu_16` | 16 | 36.8 | 0 | 83 |
| `cpu_8` | 8 | 18.4 | 0 | 40 |
| `cpu_4` | 4 | 9.2 | 0 | 20 |

Maximum wall-clock time per job: **24 hours**. One resource type per job.

### Storage paths

| Path | Quota | Purpose |
|---|---|---|
| `/home/<group>/<you>` | 25 GiB | code, scripts, small files |
| `/work/<group>/<you>` | 100 GiB | everyday working data |
| `/gs/fs` (SSD), `/gs/bs` (HDD) | purchased per group | large shared data |
| `/apps` | read-only | site-installed applications |
| `/local` | per-node, per-job | fast scratch, erased when the job ends |

### The skills (and when they fire)

| Skill / command | Fires when you… |
|---|---|
| `tsubame-configuring` | ask to set up or fix your connection |
| `tsubame-submitting-jobs` | ask to run/submit/launch a job |
| `tsubame-monitoring-jobs` | ask about job status, output, or failures |
| `tsubame-reference` | ask a factual question about TSUBAME4 |
| `/tsubame-demo` | want the guided end-to-end tour (run it explicitly) |

### Settings file

`~/.hpc-agent/tsubame.json`:

```json
{
  "ssh": {"host": "login.t4.gsic.titech.ac.jp"},
  "group": "your-tsubame-group"
}
```

Environment variables `TSUBAME_HOST` and `TSUBAME_GROUP` override the file if set.

### Official resources

For accounts, points/allocations, and policy questions the agent can't answer,
go to the **[TSUBAME portal](https://www.t4.cii.isct.ac.jp/en/)** or TSUBAME
support. The agent can always search the built-in guide — just ask.
