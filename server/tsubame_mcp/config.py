"""Configuration for the tsubame MCP servers.

Settings come from, in order of precedence:
  1. Environment variables (TSUBAME_*)
  2. The user config file ~/.tsubame/config.json (path override: TSUBAME_CONFIG)
  3. Defaults

The config file is created with the help of the `tsubame-configuring` skill:

    {
      "ssh": {"host": "tsubame"},
      "group": "your-tsubame-group",
      "embedding": {"base_url": "...", "model": "...", "api_key": "..."}
    }

`ssh.host` is an alias from ~/.ssh/config or a plain user@hostname; key-based
auth is assumed (no credentials are stored here). `group` is the default TSUBAME
group (the `-g` argument) charged in TSUBAME points for jobs that don't set one
explicitly. When no group is available the job submits as a free "trial run"
(no `-g`; ≤2 resource-type units, 3 minutes).

Documentation search ships as a BM25 keyword index by default: TSUBAME4 is at
Institute of Science Tokyo, so the shared RIKEN embedding endpoint does not
apply. EMBED_BASE_URL / EMBED_MODEL are overridable constants — point them at an
embedding endpoint and rebuild the index (rag.ingest) to enable semantic search.
"""
import json
import os
from contextlib import ExitStack
from functools import lru_cache
from importlib import resources
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("TSUBAME_CONFIG", "~/.tsubame/config.json")).expanduser()


def _file_config() -> dict:
    """The parsed config file, or {} if absent. Raises on malformed JSON."""
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Malformed config file {CONFIG_PATH}: {e}") from e


def ssh_host() -> str:
    """SSH destination for the TSUBAME4 front-end (alias or user@hostname).

    The default `tsubame` is an alias the `tsubame-configuring` skill adds to
    ~/.ssh/config (→ login.t4.gsic.titech.ac.jp with the user's key).
    """
    return (os.environ.get("TSUBAME_HOST")
            or _file_config().get("ssh", {}).get("host")
            or "tsubame")


def default_group() -> str | None:
    """Default TSUBAME group (the `-g` argument) for jobs that don't set one.

    Jobs are billed in TSUBAME points to a group. When a JobSpec leaves
    attributes.account unset this provides the fallback; if it is also None the
    job submits without `-g` as a free trial run. Override via TSUBAME_GROUP.
    """
    return (os.environ.get("TSUBAME_GROUP")
            or _file_config().get("group")
            or None)


# --- Embedding endpoint -----------------------------------------------------
# TSUBAME4 ships a BM25-only docs index (no embeddings.npy), so these constants
# are empty by default and docs search uses keyword matching. To enable semantic
# search, set them to a reachable endpoint + model and rebuild the index with
# `python -m tsubame_mcp.rag.ingest` (a committed embeddings.npy is tied to the
# exact model, so the model must not change between ingest and query time).

EMBED_BASE_URL = ""
EMBED_MODEL = ""


def embed_api_key() -> str:
    """API key for the embedding endpoint (the only user-configurable embedding setting).

    Resolved in order: TSUBAME_EMBED_API_KEY, then RCCS_EMBED_API_KEY (a shared
    fallback for users running several R-CCS-family plugins), then
    embedding.api_key in the config file. Empty string means no auth header is
    sent — and with no configured endpoint, docs search stays on BM25.
    """
    file = _file_config().get("embedding", {})
    return (os.environ.get("TSUBAME_EMBED_API_KEY")
            or os.environ.get("RCCS_EMBED_API_KEY")
            or file.get("api_key") or "")


# --- Static data ------------------------------------------------------------

_RESOURCE_STACK = ExitStack()


def _bundled_data_dir() -> Path:
    """Filesystem path to package data, including zip-safe extraction fallback."""
    data = resources.files("tsubame_mcp") / "data"
    return _RESOURCE_STACK.enter_context(resources.as_file(data))


_DATA_DIR = _bundled_data_dir()

DOCS_INDEX_DIR = Path(os.environ.get("TSUBAME_DOCS_INDEX", _DATA_DIR / "docs_index"))
# The documentation source is our own original packaged guide — facts in our own
# words, not a copy of the vendor User's Guide — so it is committed and the index
# can be freely distributed. `rag.ingest` chunks it by heading.
DOCS_SOURCE = Path(os.environ.get("TSUBAME_DOCS_SOURCE", _DATA_DIR / "tsubame_guide.md"))
DOCS_SITE_BASE = "https://www.t4.cii.isct.ac.jp/en/"


@lru_cache(maxsize=1)
def load_cluster_config() -> dict:
    """Load the static TSUBAME4 description (resource types, modules, storage)."""
    path = Path(os.environ.get("TSUBAME_CLUSTER_CONFIG", _DATA_DIR / "tsubame_config.json"))
    with open(path) as f:
        return json.load(f)
