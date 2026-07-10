# Quickstart — your first TSUBAME4 job in ~5 minutes

**What this is:** Tsubame4Agent lets you use the TSUBAME4 supercomputer by
**talking to an AI agent in plain English**. Instead of learning Linux commands
and the `qsub` job scheduler, you say things like *"run my script on one GPU for
an hour"* and the agent does it for you over your SSH connection.

This page gets you from zero to a real (free) job. For the full manual, see
[`docs/USER_GUIDE.md`](docs/USER_GUIDE.md).

---

## 1. Before you start

You need four things (one-time):

1. **A TSUBAME4 account** at Institute of Science Tokyo. If you don't have one,
   apply through the [TSUBAME portal](https://www.t4.cii.isct.ac.jp/en/).
2. **Your SSH public key registered on the portal.** TSUBAME4 only allows
   key-based login — no passwords. Register your key before your first login.
   (If you can already run `ssh login.t4.gsic.titech.ac.jp` from your terminal,
   you're set.)
3. **`uv`** — a small tool that launches the agent's cluster connector. Install
   with `brew install uv` (macOS) or `curl -LsSf https://astral.sh/uv/install.sh | sh`,
   then **restart** Claude Code / Codex so it sees `uv`.
4. **Claude Code** (this guide's focus) or **Codex**.

> **New to all of this?** Don't worry — you won't type any cluster commands
> yourself. The agent handles them. Read the
> [User Guide](docs/USER_GUIDE.md) for a gentle explanation of everything.

---

## 2. Install the plugin (Claude Code)

In Claude Code, run these three commands:

```
/plugin marketplace add TengxiangLii/Tsubame4-Agent
/plugin install tsubame@tsubame-marketplace
/reload-plugins
```

> **Codex:** run `codex plugin marketplace add TengxiangLii/Tsubame4-Agent`,
> then open `/plugins` and install `tsubame`.

---

## 3. Connect it to your account

Just tell the agent, in plain English:

> **Set up my TSUBAME4 connection.**

It will walk you through a short setup (which SSH host/alias to use, your TSUBAME
*group* for billing) and write a small settings file at `~/.hpc-agent/tsubame.json`
that looks like this:

```json
{
  "ssh": {"host": "login.t4.gsic.titech.ac.jp"},
  "group": "your-tsubame-group"
}
```

Then check the connection:

> **Run the TSUBAME doctor / check my connection.**

You want to see `✓ ssh` and `✓ grid engine`.

---

## 4. Run your first job — free, no cost

TSUBAME4 charges compute time in "TSUBAME points," but there's a **free trial
run** for testing. The built-in demo uses it. Just say:

> **/tsubame-demo**

The agent will, step by step: describe the machine, show how busy it is, search
the docs, poke around your files, and then **submit a tiny free test job** and
read back its output. A successful run prints the compute node's name and its
**four NVIDIA H100 GPUs** — proof the whole chain works end to end.

Nothing in the demo spends any points.

---

## 5. What next

- Read the **[User Guide](docs/USER_GUIDE.md)** — what you can do, dozens of
  example prompts, and troubleshooting.
- Or just start asking. Try: *"How many TSUBAME points does my group have left?"*
  or *"Show me what's in my home directory."*
