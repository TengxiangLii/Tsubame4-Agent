"""Build the docs index from the bundled guide.

    python -m tsubame_mcp.ingest              # chunks + embeddings (needs an API key)
    python -m tsubame_mcp.ingest --no-embed   # keyword-only index

Thin wrapper over `hpc_agent_core.rag.ingest`: importing config first
registers the machine's settings (guide path, embedding endpoint, docs_cite_url)
before the generic ingest reads them. End users never need this — the built
index is committed as package data; re-run it only after editing the guide.

No shared embedding endpoint ships for TSUBAME4 (embed_base_url/embed_model
are fixed blank in config.py's configure() call), so this always writes a
BM25-only index regardless of --no-embed.
"""
from hpc_agent_core.rag.ingest import main
from tsubame_mcp import config  # noqa: F401 -- registers settings via configure()

if __name__ == "__main__":
    main()
