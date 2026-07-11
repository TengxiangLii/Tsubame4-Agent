"""Health checks for the TSUBAME4 plugin.

    python -m tsubame_mcp.doctor

Reuses core's config/guide/docs-index/embedding checks, but writes a local
SSH+scheduler check: core's `check_ssh()` requires the scheduler probe's
output to *start with* a fixed scheduler-name string (fits Slurm's `sinfo
--version` -> "slurm ..."), but Grid Engine's `qstat -help` prints usage
text with no such predictable prefix — the same shape mismatch Irene's
Bridge scheduler and cell2026's dual-scheduler port both hit, solved the
same way each time: a local check reusing core's ok_token pattern but not
its startswith assumption.
"""
import sys

from hpc_agent_core import config
from hpc_agent_core.doctor import (
    OK,
    FAIL,
    check_config_file,
    check_docs_guide_bundled,
    check_docs_index,
    check_embedding,
)
from tsubame_mcp import config as _config  # noqa: F401 -- registers via configure()


def check_ssh_and_scheduler() -> bool:
    from hpc_agent_core.middleware import run_command
    host = config.ssh_host()
    ok_token = f"{host}-doctor-ok".replace(" ", "-")
    try:
        output = run_command(f"echo {ok_token} && hostname")
    except Exception as e:
        print(f"{FAIL} ssh ({host}): {e}")
        return False
    if ok_token not in output:
        print(f"{FAIL} ssh ({host}): unexpected response: {output[:200]}")
        return False
    print(f"{OK} ssh ({host}): connected to {output.strip().splitlines()[-1]}")

    try:
        run_command("qstat -help >/dev/null 2>&1 || qstat -xml >/dev/null")
    except Exception as e:
        print(f"{FAIL} grid engine: qstat not available: {e}")
        return False
    print(f"{OK} grid engine (Altair Grid Engine): qstat responds")
    return True


def main() -> int:
    results = [
        check_config_file(),
        check_ssh_and_scheduler(),
        check_docs_guide_bundled(),
        check_docs_index(),
        check_embedding(),
    ]
    if all(results):
        print("\nAll checks passed.")
        return 0
    print("\nSome checks FAILED — see above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
