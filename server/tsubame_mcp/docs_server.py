"""MCP server for searching the TSUBAME4.0 documentation guide.

Read-only and needs no SSH access. The generic docs-search tools
(search_docs / list_doc_sections / read_doc_section) live in
`hpc_agent_core.docs_server`; this module only imports the machine's config
(registering its settings), names the FastMCP instance, and serves it.
"""
from mcp.server.fastmcp import FastMCP

from hpc_agent_core.docs_server import build
from hpc_agent_core.serving import serve
from tsubame_mcp import config  # noqa: F401 -- registers settings via configure()

mcp = FastMCP("tsubame-docs")
build(mcp)


def main():
    serve(mcp)


if __name__ == "__main__":
    main()
