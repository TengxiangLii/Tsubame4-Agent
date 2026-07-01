"""MCP server for TSUBAME4.0, modeled on the IRI Facility API.

Tool groups mirror the IRI resource groups (facility, status, account, compute,
filesystem); each operation is executed on a TSUBAME4 login node over SSH via
remotemanager, since TSUBAME4 does not expose a REST facility API itself.
Coverage of the full API is tracked in IRI_CHECKLIST.md at the repo root.
"""
import shlex

from mcp.server.fastmcp import FastMCP

from tsubame_mcp import compute, config
from tsubame_mcp.middleware import quote_path, run_command, write_remote_file
from tsubame_mcp.models import CompressionType, Job, JobSpec
from tsubame_mcp.serving import serve

mcp = FastMCP("tsubame-hpc")

RESOURCE_ID = "tsubame4"


def _check_resource(resource_id: str) -> None:
    if resource_id != RESOURCE_ID:
        raise ValueError(f"Unknown resource '{resource_id}'; this server manages '{RESOURCE_ID}'")


# === facility ================================================================

@mcp.tool()
def get_facility() -> dict:
    """Describe the TSUBAME4 facility: resource types, modules, storage, conventions.

    Static reference data (no SSH round-trip). TSUBAME4 is a GPU-first system:
    240 nodes, each with 2x AMD EPYC 9654 (192 cores) and 4x NVIDIA H100. Jobs
    are sized by resource type (node_f, gpu_1, cpu_4, ...). (IRI: GET /facility)
    """
    return config.load_cluster_config()


# === status ==================================================================

@mcp.tool()
def get_resources() -> list[dict]:
    """List compute resources and their live state. (IRI: GET /status/resources)

    Returns the TSUBAME4 resource with a per-queue slot summary (used/reserved/
    available/total, from `qstat -g c`) plus the static resource-type table.
    """
    return [_resource_detail()]


@mcp.tool()
def get_resource(resource_id: str = RESOURCE_ID) -> dict:
    """Get detailed state for a single resource. (IRI: GET /status/resources/{resource_id})"""
    _check_resource(resource_id)
    return _resource_detail()


def _resource_detail() -> dict:
    """Live cluster-queue load from `qstat -g c` + the static resource types."""
    queues = []
    try:
        summary = run_command("qstat -g c")
    except RuntimeError:
        summary = ""
    for line in summary.strip().splitlines():
        parts = line.split()
        # header: CLUSTER QUEUE CQLOAD USED RES AVAIL TOTAL aoACDS cdsuE
        if not parts or parts[0] == "CLUSTER" or parts[0].startswith("-"):
            continue
        if len(parts) >= 7 and parts[3].isdigit():
            queues.append({
                "queue": parts[0],
                "load": parts[1],
                "used": int(parts[2]),
                "reserved": int(parts[3]),
                "available": int(parts[4]),
                "total": int(parts[5]),
            })
    cfg = config.load_cluster_config()
    return {
        "id": RESOURCE_ID,
        "type": "compute",
        "description": "Institute of Science Tokyo TSUBAME4.0 (AMD EPYC + NVIDIA H100; GPU-first, Altair Grid Engine)",
        "queues": queues,
        "resource_types": cfg.get("resource_types", []),
    }


# === account =================================================================

def _group_points(group: str) -> dict | None:
    """Parse `t4-user-info group point -g <group>` -> {deposit, balance}."""
    try:
        output = run_command(f"t4-user-info group point -g {shlex.quote(group)}")
    except RuntimeError:
        return None
    for line in output.strip().splitlines():
        parts = line.split()
        # rows: gid  group_name  deposit  balance
        if len(parts) >= 4 and parts[0].isdigit():
            return {"gid": parts[0], "group": parts[1],
                    "deposit": parts[2], "balance": parts[3]}
    return None


@mcp.tool()
def get_projects() -> list[dict]:
    """List the TSUBAME groups (projects) the current user can charge jobs to.
    (IRI: GET /account/projects)

    Each project id is a TSUBAME group name, used as JobAttributes.account (the
    qsub `-g` argument). Groups come from the user's Unix group membership;
    TSUBAME project groups are the `tg*` ones (e.g. tga-…), so system groups
    (tsubame-users, sys_*, tgz-edu) are filtered out.
    """
    output = run_command("id -Gn")
    skip = {"tsubame-users", "tgz-edu"}
    groups = [g for g in output.split()
              if g.startswith("tg") and g not in skip]
    return [{"id": g} for g in groups]


@mcp.tool()
def get_project(project_id: str) -> dict:
    """Get details for one project (TSUBAME group), including its point balance.
    (IRI: GET /account/projects/{id})
    """
    points = _group_points(project_id)
    result: dict = {"id": project_id}
    if points:
        result["points"] = {"deposit": points["deposit"], "balance": points["balance"]}
        result["gid"] = points["gid"]
    return result


@mcp.tool()
def get_project_allocations(project_id: str) -> dict:
    """Get a project's TSUBAME-point allocation and remaining balance.
    (IRI: GET /account/projects/{id}/allocations)

    TSUBAME4 bills compute in TSUBAME points held per group; `deposit` is the
    current committed rate and `balance` the remaining points.
    """
    points = _group_points(project_id)
    if not points:
        raise ValueError(f"No point information for group '{project_id}' "
                         f"(check the group name and your membership)")
    return {
        "project": project_id,
        "unit": "TSUBAME points",
        "deposit": points["deposit"],
        "balance": points["balance"],
    }


@mcp.tool()
def get_user_allocations() -> list[dict]:
    """Point balances for each TSUBAME group the current user belongs to.
    (IRI: GET /account/allocations)
    """
    allocations = []
    for project in get_projects():
        points = _group_points(project["id"])
        if points:
            allocations.append({
                "project": project["id"],
                "unit": "TSUBAME points",
                "deposit": points["deposit"],
                "balance": points["balance"],
            })
    return allocations


# === compute =================================================================

@mcp.tool()
def submit_job(spec: JobSpec, resource_id: str = RESOURCE_ID) -> dict:
    """Submit a job described by a JobSpec. (IRI: POST /compute/job/{resource_id})

    The spec is rendered as a Grid Engine script (kept under ~/.tsubame/jobs/ on
    the cluster for auditability) and submitted with qsub. Returns job_id, the
    script path, and the charged group. TSUBAME4 notes: size the job with
    resources.resource_type (node_f full node with 4 GPUs is the default; gpu_1
    for a single GPU; cpu_4..cpu_160 for CPU-only) and resource_count;
    attributes.account is the TSUBAME group charged in points (falls back to the
    configured default, or submits as a free trial run if none is set); load
    software in pre_launch (e.g. 'module purge && module load cuda'); executable
    may be a shell line and launcher an MPI prefix (mpirun/mpiexec.hydra).
    """
    _check_resource(resource_id)
    return compute.submit(spec)


@mcp.tool()
def get_job_status(job_id: str, resource_id: str = RESOURCE_ID) -> Job:
    """Get the normalized status of one job. (IRI: GET /compute/status/...)

    state is the normalized IRI state (QUEUED/ACTIVE/COMPLETED/FAILED/CANCELED);
    native_state is Grid Engine's (qstat code, or qacct for finished jobs). Job
    stdout defaults to <name>.o<job_id> and stderr to <name>.e<job_id> in the
    submit directory — read them with fs_tail or fs_view.
    """
    _check_resource(resource_id)
    jobs = compute.get_statuses([job_id])
    if not jobs:
        raise ValueError(f"Job {job_id} not found")
    return jobs[0]


@mcp.tool()
def get_job_statuses(job_ids: list[str], resource_id: str = RESOURCE_ID) -> list[Job]:
    """Get statuses for several jobs at once, or the current user's live (queued
    + running) jobs when job_ids is empty. (IRI: POST /compute/status/{resource_id})
    """
    _check_resource(resource_id)
    if job_ids:
        return compute.get_statuses(job_ids)
    return compute.get_recent_statuses()


@mcp.tool()
def update_job(
    job_id: str,
    time_limit: str | None = None,
    name: str | None = None,
    priority: int | None = None,
    hold_jid: str | None = None,
    resource_id: str = RESOURCE_ID,
) -> Job:
    """Update a queued job with qalter. (IRI: PUT /compute/job/{resource_id}/{job_id})

    All fields are optional — only supplied ones are changed. time_limit is the
    new wall time (h_rt) as HH:MM:SS; priority is -5/-4/-3. Most changes only
    apply while the job is still queued.
    """
    _check_resource(resource_id)
    args = []
    if time_limit is not None:
        args.append(f"-l h_rt={shlex.quote(time_limit)}")
    if name is not None:
        args.append(f"-N {shlex.quote(name)}")
    if priority is not None:
        args.append(f"-p {int(priority)}")
    if hold_jid is not None:
        args.append(f"-hold_jid {shlex.quote(hold_jid)}")
    if not args:
        raise ValueError("No fields to update — supply at least one argument")
    run_command(f"qalter {' '.join(args)} {shlex.quote(job_id)}")
    jobs = compute.get_statuses([job_id])
    if not jobs:
        raise ValueError(f"Job {job_id} not found after update")
    return jobs[0]


@mcp.tool()
def cancel_job(job_id: str, resource_id: str = RESOURCE_ID) -> Job | str:
    """Cancel a queued or running job with qdel and report its resulting state.
    (IRI: DELETE /compute/cancel/{resource_id}/{job_id})
    """
    _check_resource(resource_id)
    return compute.cancel(job_id)


# === filesystem ==============================================================
# Paths are relative to the home directory unless absolute.

@mcp.tool()
def fs_ls(path: str = ".", show_hidden: bool = False) -> str:
    """List a directory on the cluster. (IRI: GET /filesystem/ls)"""
    flags = "-la" if show_hidden else "-l"
    return run_command(f"ls {flags} {quote_path(path)}")


@mcp.tool()
def fs_stat(path: str) -> str:
    """Stat a file or directory on the cluster. (IRI: GET /filesystem/stat)"""
    return run_command(f"stat {quote_path(path)}")


@mcp.tool()
def fs_view(path: str) -> str:
    """Read a whole text file on the cluster (output capped at 200KB).
    (IRI: GET /filesystem/view) For large files use fs_head/fs_tail.
    """
    return run_command(f"cat {quote_path(path)}")


@mcp.tool()
def fs_head(path: str, lines: int = 50) -> str:
    """Read the first lines of a file on the cluster. (IRI: GET /filesystem/head)"""
    return run_command(f"head -n {int(lines)} {quote_path(path)}")


@mcp.tool()
def fs_tail(path: str, lines: int = 50) -> str:
    """Read the last lines of a file on the cluster — e.g. a job's
    <name>.o<job_id> output. (IRI: GET /filesystem/tail)
    """
    return run_command(f"tail -n {int(lines)} {quote_path(path)}")


@mcp.tool()
def fs_mkdir(path: str) -> str:
    """Create a directory (and parents) on the cluster. (IRI: POST /filesystem/mkdir)"""
    quoted = quote_path(path)
    return run_command(f"mkdir -p {quoted} && echo created: $(realpath {quoted})")


@mcp.tool()
def fs_upload(path: str, content: str, binary: bool = False) -> str:
    """Write a file on the cluster, creating parent directories.
    (IRI: POST /filesystem/upload — max 5 MB)

    For text files pass the content directly (binary=False, the default).
    For binary files pass the content as base64 and set binary=True; it will
    be decoded before writing. Use fs_compress + fs_download for files over 5 MB.
    """
    import base64 as _b64
    raw: str | bytes
    if binary:
        raw = _b64.b64decode(content)
    else:
        raw = content
    size = len(raw) if isinstance(raw, bytes) else len(raw.encode())
    if size > 5 * 1024 * 1024:
        raise ValueError(f"Content is {size:,} bytes — exceeds 5 MB upload limit.")
    abs_path = write_remote_file(path, raw)
    return f"Wrote {size:,} bytes to {abs_path}"


@mcp.tool()
def fs_checksum(path: str) -> str:
    """SHA-256 checksum of a file on the cluster. (IRI: GET /filesystem/checksum)"""
    return run_command(f"sha256sum {quote_path(path)}")


@mcp.tool()
def fs_download(path: str) -> str:
    """Download a small file from the cluster as base64. (IRI: GET /filesystem/download)

    Capped at 5 MB (matching IRI spec). Use fs_compress first for larger files,
    then download the archive. The caller can base64-decode and write locally.
    """
    size_out = run_command(f"stat -c %s {quote_path(path)}")
    size = int(size_out.strip())
    if size > 5 * 1024 * 1024:
        raise ValueError(
            f"File is {size:,} bytes — exceeds 5 MB limit. "
            f"Compress it first with fs_compress, or transfer with: "
            f"scp {config.ssh_host()}:{path} ."
        )
    return run_command(f"base64 {quote_path(path)}")


@mcp.tool()
def fs_cp(src: str, dst: str) -> str:
    """Copy a file or directory on the cluster. (IRI: POST /filesystem/cp)

    Uses cp -r so it works for both files and directories.
    """
    return run_command(f"cp -r {quote_path(src)} {quote_path(dst)} && echo ok")


@mcp.tool()
def fs_mv(src: str, dst: str) -> str:
    """Move or rename a file or directory on the cluster. (IRI: POST /filesystem/mv)

    Destructive — the source path will no longer exist after this call.
    """
    return run_command(f"mv {quote_path(src)} {quote_path(dst)} && echo ok")


@mcp.tool()
def fs_chmod(path: str, mode: str) -> str:
    """Change file permissions on the cluster. (IRI: PUT /filesystem/chmod)

    mode is an octal string, e.g. '755' or '644'.
    """
    return run_command(f"chmod {shlex.quote(mode)} {quote_path(path)} && echo ok")


@mcp.tool()
def fs_chown(path: str, owner: str = "", group: str = "") -> str:
    """Change file ownership on the cluster. (IRI: PUT /filesystem/chown)

    Supply owner, group, or both. Normal users can only change group to one
    they belong to; changing owner requires root.
    """
    if not owner and not group:
        raise ValueError("Provide at least one of owner or group")
    spec = owner + (":" + group if group else "")
    return run_command(f"chown {shlex.quote(spec)} {quote_path(path)} && echo ok")


@mcp.tool()
def fs_symlink(path: str, link_path: str) -> str:
    """Create a symbolic link on the cluster. (IRI: POST /filesystem/symlink)

    path is the target; link_path is the new symlink to create.
    """
    return run_command(
        f"ln -s {quote_path(path)} {quote_path(link_path)} && echo ok"
    )


_COMPRESSION_FLAGS = {
    CompressionType.NONE: "",
    CompressionType.GZIP: "z",
    CompressionType.BZIP2: "j",
    CompressionType.XZ: "J",
}


@mcp.tool()
def fs_compress(
    target_path: str,
    path: str | None = None,
    match_pattern: str | None = None,
    dereference: bool = False,
    compression: CompressionType = CompressionType.GZIP,
) -> str:
    """Create an archive on the cluster. (IRI: POST /filesystem/compress)

    target_path: path of the archive to create.
    path: source file or directory (defaults to current directory).
    match_pattern: regex passed to find -regex to filter files.
    dereference: follow symlinks (-h).
    compression: gzip (default), bzip2, xz, or none.
    """
    flag = _COMPRESSION_FLAGS[compression]
    deref = "h" if dereference else ""
    tar_flags = f"-{deref}c{flag}f"

    if match_pattern:
        src = quote_path(path or ".")
        pattern = shlex.quote(match_pattern)
        cmd = (
            f"find {src} -regex {pattern} -print0 | "
            f"tar {tar_flags} {quote_path(target_path)} --null -T -"
        )
    else:
        src = quote_path(path or ".")
        cmd = f"tar {tar_flags} {quote_path(target_path)} {src}"

    return run_command(cmd + " && echo ok")


@mcp.tool()
def fs_extract(
    path: str,
    target_path: str,
    compression: CompressionType = CompressionType.GZIP,
) -> str:
    """Extract an archive on the cluster. (IRI: POST /filesystem/extract)

    path: archive file to extract.
    target_path: directory to extract into (created if absent).
    compression: gzip (default), bzip2, xz, or none.
    """
    flag = _COMPRESSION_FLAGS[compression]
    tar_flags = f"-x{flag}f"
    return run_command(
        f"mkdir -p {quote_path(target_path)} && "
        f"tar {tar_flags} {quote_path(path)} -C {quote_path(target_path)} && echo ok"
    )


# === extensions (not part of the IRI API) ====================================

@mcp.tool()
def run_command_on_cluster(command: str) -> str:
    """Run an arbitrary shell command on a TSUBAME4 login node (extension —
    not an IRI endpoint).

    Use only when no dedicated tool fits, e.g. 'module avail' to list software,
    't4-user-info group point -g <group>' to check TSUBAME points, 'qstat' to
    see the queue, or 't4-user-info disk home' for quota. Runs under a login
    shell from the home directory; returns stdout+stderr. Do not run heavy
    computation on the login node — submit a job instead.
    """
    return run_command(command)


def main():
    serve(mcp)


if __name__ == "__main__":
    main()
