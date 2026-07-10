"""Live smoke test: drive both MCP servers over stdio, exactly as Claude Code does.

Usage:  python tests/smoke.py [--job]

Without --job: docs search + facility/status/queue queries (read-only).
With --job: additionally submits a tiny free *trial-run* job via a JobSpec (no
TSUBAME group, <=3 min), polls it to completion, and tails its output.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER_DIR = Path(__file__).resolve().parent.parent
RUN_SH = SERVER_DIR / "run.sh"


async def call(session: ClientSession, tool: str, args: dict | None = None) -> str:
    result = await session.call_tool(tool, args or {})
    text = "\n".join(c.text for c in result.content if c.type == "text")
    status = "ERROR" if result.isError else "ok"
    print(f"--- {tool} [{status}] ---\n{text[:1200]}\n")
    if result.isError:
        raise RuntimeError(f"{tool} failed: {text}")
    return text


async def docs_checks() -> None:
    params = StdioServerParameters(command=str(RUN_SH), args=["tsubame_mcp.docs_server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = [t.name for t in (await session.list_tools()).tools]
            print(f"tsubame-docs tools: {tools}\n")
            await call(session, "search_docs",
                       {"query": "how are jobs sized and billed", "top_k": 2})


async def hpc_checks(submit: bool) -> None:
    params = StdioServerParameters(command=str(RUN_SH), args=["tsubame_mcp.hpc_server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = [t.name for t in (await session.list_tools()).tools]
            print(f"tsubame-hpc tools: {tools}\n")

            await call(session, "get_facility")
            await call(session, "get_resources")
            await call(session, "get_resource", {"resource_id": "tsubame4"})
            await call(session, "get_projects")
            from tsubame_mcp import config as _cfg
            grp = _cfg.default_group()
            if grp:
                await call(session, "get_project", {"project_id": grp})
                await call(session, "get_project_allocations", {"project_id": grp})
            await call(session, "get_user_allocations")
            await call(session, "get_job_statuses", {"job_ids": []})

            # filesystem utilities — fs_upload/fs_download transfer via rsync
            # (scp fallback) against a real local file, not inline content.
            import hashlib
            import tempfile

            with tempfile.TemporaryDirectory() as tmpdir:
                local_src = Path(tmpdir) / "tsubame-smoke.txt"
                local_src.write_text("smoke test\n")
                local_sha = hashlib.sha256(local_src.read_bytes()).hexdigest()

                upload_result = await call(session, "fs_upload",
                    {"path": "/tmp/tsubame-smoke.txt", "local_path": str(local_src)})
                assert json.loads(upload_result)["verified"], "fs_upload sha256 mismatch"

                csum1 = await call(session, "fs_checksum", {"path": "/tmp/tsubame-smoke.txt"})
                assert csum1.split()[0] == local_sha, "fs_checksum doesn't match uploaded content"

                local_dst = Path(tmpdir) / "tsubame-smoke-downloaded.txt"
                download_result = await call(session, "fs_download",
                    {"path": "/tmp/tsubame-smoke.txt", "local_path": str(local_dst)})
                assert json.loads(download_result)["verified"], "fs_download sha256 mismatch"
                assert local_dst.read_text() == "smoke test\n", "download content mismatch"

            await call(session, "fs_cp",
                       {"src": "/tmp/tsubame-smoke.txt", "dst": "/tmp/tsubame-smoke-copy.txt"})
            csum2 = await call(session, "fs_checksum", {"path": "/tmp/tsubame-smoke-copy.txt"})
            assert csum1.split()[0] == csum2.split()[0], "checksum mismatch after cp"
            await call(session, "fs_mv",
                       {"src": "/tmp/tsubame-smoke-copy.txt", "dst": "/tmp/tsubame-smoke-moved.txt"})
            csum3 = await call(session, "fs_checksum", {"path": "/tmp/tsubame-smoke-moved.txt"})
            assert csum1.split()[0] == csum3.split()[0], "checksum changed across mv"
            await call(session, "fs_chmod", {"path": "/tmp/tsubame-smoke.txt", "mode": "644"})
            await call(session, "fs_symlink",
                       {"path": "/tmp/tsubame-smoke.txt", "link_path": "/tmp/tsubame-smoke-link.txt"})
            await call(session, "fs_compress",
                       {"path": "/tmp/tsubame-smoke.txt",
                        "target_path": "/tmp/tsubame-smoke.tar.gz", "compression": "gzip"})
            await call(session, "fs_extract",
                       {"path": "/tmp/tsubame-smoke.tar.gz",
                        "target_path": "/tmp/tsubame-smoke-extracted", "compression": "gzip"})
            await call(session, "run_command_on_cluster",
                       {"command": "rm -rf /tmp/tsubame-smoke*.txt /tmp/tsubame-smoke.tar.gz "
                                   "/tmp/tsubame-smoke-extracted"})

            if not submit:
                return

            # A free trial run: NO group (account) => no points charged, capped at
            # 2 units / 3 minutes. This exercises submit -> poll -> read output.
            spec = {
                "name": "tsubame-smoke",
                "executable": "hostname && nvidia-smi -L && nproc",
                "resources": {"node_count": 1},
                "attributes": {
                    "duration": "0:03:00",
                    "account": "",  # "" => free trial run
                    "custom_attributes": {"resource_type": "node_f"},
                },
            }
            out = await call(session, "submit_job", {"spec": spec})
            job_id = json.loads(out)["job_id"]
            print(f">>> submitted trial-run job {job_id}; polling...\n")

            state = "unknown"
            for _ in range(20):
                status_text = await call(session, "get_job_status", {"job_id": job_id})
                job = json.loads(status_text)
                state = job["status"]["state"]
                if state in ("completed", "failed", "canceled"):
                    break
                await asyncio.sleep(15)

            assert state == "completed", f"job ended {state}"
            await call(session, "fs_tail",
                       {"path": f"tsubame-smoke.o{job_id}", "lines": 20})


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", action="store_true",
                        help="Also submit and verify a tiny free trial-run job.")
    args = parser.parse_args()

    await docs_checks()
    await hpc_checks(submit=args.job)
    print("SMOKE TEST PASSED")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
