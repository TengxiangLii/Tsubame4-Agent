"""Settings for the TSUBAME4 MCP plugin.

This module is a thin registration layer over `hpc_agent_core.config`: it
calls `configure(...)` once, at import time, before any other
`hpc_agent_core` module that reads config is used, then re-exports the
registered values for readability at call sites.

Settings resolve in order: environment variable > the user config file >
the registered default. The user config file lives at the common location
`~/.hpc-agent/tsubame.json` (see `hpc_agent_core.config.config_path()`).
The legacy per-machine path `~/.tsubame/config.json` is still honored if it
is the only one that exists.

Example config file:

    {
      "ssh": {"host": "tsubame"},
      "group": "your-tsubame-group"
    }

`ssh.host` is a `~/.ssh/config` alias or a plain `user@hostname`; key-based
auth is assumed (no credentials are stored here). `group` is TSUBAME4-specific
(the default `qsub -g` group) and has no core equivalent — no other machine
in this family bills jobs to a points-based group.

TSUBAME4 ships with no shared embedding endpoint (unlike the RIKEN R-CCS
family) — `embed_base_url`/`embed_model` are fixed blank in configure(), so
docs search is BM25-only. Pre-migration, the skill/README documented an
`embedding.base_url`/`embedding.model` config-file override for a
self-hosted endpoint — but the pre-migration `config.py` only ever read
`EMBED_BASE_URL`/`EMBED_MODEL` as hardcoded constants, never from the file,
so that override never actually worked. This migration doesn't resurrect
it (core's `embed_base_url()`/`embed_model()` are fixed once at
`configure()` time for every machine, matching how the rest of the family
already works) — the docs/skill wording is corrected instead of the dead
feature being reimplemented.
"""
import json
import os
from functools import lru_cache

from hpc_agent_core import config as _core

_core.configure(
    env_prefix="TSUBAME",              # -> TSUBAME_HOST, TSUBAME_CONFIG, TSUBAME_EMBED_API_KEY
    default_host="tsubame",             # ssh.host fallback: an alias in ~/.ssh/config, or user@hostname
    package="tsubame_mcp",              # matches this package's actual name (for bundled data)
    embed_base_url="",                  # blank: no shared embedding endpoint ships for TSUBAME4; BM25 by default
    embed_model="",
    docs_cite_url="",                   # blank: the guide is our own words; no live site to cite
    # No computer_defaults: the login node works with the shared bash
    # login-shell defaults (see hpc_agent_core.config._BASE_COMPUTER_DEFAULTS).
)

# Re-export the registered functions/values the rest of the package imports
# from here (kept for readability — these are just the core's registered API):
ssh_host = _core.ssh_host
embed_api_key = _core.embed_api_key
EMBED_BASE_URL = _core.embed_base_url()
EMBED_MODEL = _core.embed_model()
CONFIG_PATH = _core.config_path()
DATA_DIR = _core.data_dir()


def _file_config() -> dict:
    """The parsed config file, or {} if absent/malformed. Read at call time
    (never at import) so a missing config never blocks startup."""
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def default_group() -> str | None:
    """Default TSUBAME group (the `-g` argument) for jobs that don't set one.

    Jobs are billed in TSUBAME points to a group. When a JobSpec leaves
    attributes.account unset this provides the fallback; if it is also None
    the job submits without -g as a free trial run. Override via
    TSUBAME_GROUP. This is genuinely TSUBAME4-specific policy — no core
    equivalent, since no other machine in this family has a points-based
    group-billing model.
    """
    return (os.environ.get("TSUBAME_GROUP")
            or _file_config().get("group")
            or None)


@lru_cache(maxsize=1)
def load_cluster_config() -> dict:
    """TSUBAME4's static facts (resource types, modules, storage) — bundled
    package data, not the user's config file."""
    with open(DATA_DIR / "tsubame_config.json") as f:
        return json.load(f)
