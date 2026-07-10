---
name: tsubame-configuring
description: Use when the user wants to set up, configure, or troubleshoot Tsubame4Agent — SSH access to the TSUBAME4.0 login nodes, the default TSUBAME group, or the ~/.hpc-agent/tsubame.json file. Also use when tsubame tools fail with connection or group errors.
---

# Configuring Tsubame4Agent

Settings live in `~/.hpc-agent/tsubame.json` (the common directory shared by
every hpc-agent-core plugin). Env vars `TSUBAME_HOST`/`TSUBAME_GROUP` override
it:

```json
{
  "ssh": {"host": "tsubame"},
  "group": "your-tsubame-group"
}
```

A legacy `~/.tsubame/config.json` is still read if it's the only config present.

## Guided setup — interview the user, then write the file

Read the existing `~/.hpc-agent/tsubame.json` first (if any) and only ask about
what's missing or being changed.

1. **SSH** — ask how they reach a TSUBAME4 login node:
   - An alias in `~/.ssh/config` (recommended) → `"host": "<alias>"`. Offer to
     add a block like:
     ```
     Host tsubame
       HostName login.t4.gsic.titech.ac.jp
       User ux00000
       IdentityFile ~/.ssh/t4-key
     ```
     (`login.t4.gsic.titech.ac.jp` round-robins to login1/login2.)
   - Otherwise username + hostname → `"host": "ux00000@login.t4.gsic.titech.ac.jp"`.
   - Verify with: `ssh -o BatchMode=yes <host> 'echo ok'` (BatchMode matters —
     the MCP server cannot answer password prompts; key-based auth is required.
     Public keys are registered on the TSUBAME Portal:
     https://www.t4.cii.isct.ac.jp/en/).
2. **Default TSUBAME group** — jobs are billed in TSUBAME points to a group via
   `qsub -g <group>`. Ask for the group name and store it as `"group"`. A JobSpec
   can override it per job (an explicit empty string forces a free trial run
   even when a default is configured). If the user has no group yet (or wants
   to test), leave it unset: jobs then submit as free **trial runs** (2 units,
   3 min, no charge). Check a group's balance with
   `t4-user-info group point -g <group>`.
3. **No embedding endpoint to configure**. Docs search ships as a BM25 keyword
   index — TSUBAME4 is at Institute of Science Tokyo, so no shared embedding
   endpoint is bundled the way the RIKEN R-CCS family has. BM25 works fully
   offline and needs no configuration; there is no per-user override for a
   custom endpoint (this matches the rest of the machine family, where the
   embedding endpoint/model are fixed once, not user-configurable).
4. **Write the file**, then `chmod 600 ~/.hpc-agent/tsubame.json`. Never commit
   it or echo any key back in conversation.
5. **Validate** with the doctor (checks config, SSH, Grid Engine, docs index):
   ```bash
   uv tool run --quiet --from ./server tsubame-doctor
   ```
   (After publishing, the `git+https://…@main#subdirectory=server` form works too.)

## Notes

- Settings are read per-call, so a group change applies immediately; an SSH host
  change needs the tsubame-hpc server restarted (reconnect MCP servers or restart
  the client).
- Key-based SSH only — register the public key on the TSUBAME Portal first. Do not
  run heavy work on the login nodes.
