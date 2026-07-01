"""JobSpec -> Altair Grid Engine translation and status parsing (IRI compute backend).

TSUBAME4 runs Altair Grid Engine: jobs are `#$`-directive shell scripts submitted
with `qsub`, live state comes from `qstat` and finished-job state from `qacct`,
and cancellation is `qdel`. Jobs are billed to a TSUBAME group via the qsub `-g`
argument; a submission with no `-g` runs as a free "trial run" (<=2 units, 3 min).
"""
import re
import shlex
import time

from tsubame_mcp import config
from tsubame_mcp.middleware import run_command, write_remote_file
from tsubame_mcp.models import (
    Job,
    JobSpec,
    JobState,
    JobStatus,
    map_ge_final_state,
    map_ge_state,
)


def _duration_to_hms(duration: int | str) -> str:
    """Convert an IRI duration (int seconds or [[HH:]MM:]SS string) to h_rt HH:MM:SS."""
    if isinstance(duration, str):
        return duration
    h, rem = divmod(int(duration), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def render_script(spec: JobSpec) -> str:
    """Render a JobSpec as a TSUBAME4 Grid Engine job script.

    The `-g` group is a qsub command-line argument (not a script directive, per
    the User's Guide) and is added in submit(), not here.
    """
    res = spec.resources
    attr = spec.attributes

    lines = ["#!/bin/sh"]
    # Working directory: -cwd runs in the submit dir; -wd sets an explicit one.
    if spec.directory:
        lines.append(f"#$ -wd {shlex.quote(spec.directory)}")
    else:
        lines.append("#$ -cwd")

    lines.append(f"#$ -l {res.resource_type}={res.resource_count}")
    lines.append(f"#$ -l h_rt={_duration_to_hms(attr.duration)}")
    lines.append(f"#$ -N {shlex.quote(spec.name)}")
    lines.append(f"#$ -p {attr.priority}")

    if attr.queue_name:
        lines.append(f"#$ -q {shlex.quote(attr.queue_name)}")
    if attr.array:
        lines.append(f"#$ -t {attr.array}")
    if attr.hold_jid:
        lines.append(f"#$ -hold_jid {shlex.quote(attr.hold_jid)}")
    if attr.reservation_id:
        lines.append(f"#$ -ar {shlex.quote(attr.reservation_id)}")
    if spec.stdout_path:
        lines.append(f"#$ -o {shlex.quote(spec.stdout_path)}")
    if spec.stderr_path:
        lines.append(f"#$ -e {shlex.quote(spec.stderr_path)}")
    if spec.inherit_environment:
        # -V forwards the submission environment. Note the TSUBAME4 caveat: with
        # -V, module load can misbehave, so scripts should `module purge` first
        # (pre_launch) — and LD_LIBRARY_PATH/LD_PRELOAD are never forwarded.
        lines.append("#$ -V")
    # GPU compute mode is a job-level environment variable consumed by the site
    # prolog; only valid for node_f/node_h/node_q/gpu_1.
    if res.gpu_compute_mode is not None:
        lines.append(f"#$ -v GPU_COMPUTE_MODE={int(res.gpu_compute_mode)}")

    for key, val in attr.custom_attributes.items():
        lines.append(f"#$ -{key} {val}")

    lines.append("")

    for key, value in spec.environment.items():
        lines.append(f"export {key}={shlex.quote(value)}")
    if res.cpu_cores_per_process and "OMP_NUM_THREADS" not in spec.environment:
        # Threaded code must be told its thread count or it runs with the wrong one.
        lines.append(f"export OMP_NUM_THREADS={res.cpu_cores_per_process}")

    if spec.pre_launch:
        lines.append(spec.pre_launch)

    command = spec.executable
    if spec.arguments:
        command += " " + " ".join(shlex.quote(a) for a in spec.arguments)

    if spec.container:
        # TSUBAME4 provides Apptainer; wrap the command in `apptainer exec`,
        # bind-mounting site storage and enabling GPUs when the type provides them.
        c = spec.container
        from tsubame_mcp.models import RESOURCE_TYPES
        flags = ["-B", "/gs", "-B", "/apps", "-B", "/home"]
        if RESOURCE_TYPES.get(res.resource_type, {}).get("gpus"):
            flags.append("--nv")
        for m in c.volume_mounts:
            bind = f"{m.source}:{m.target}" + (":ro" if m.read_only else "")
            flags += ["-B", shlex.quote(bind)]
        # Double-quote image so shell variables like $HOME expand in the script.
        flags.append(f'"{c.image}"')
        command = ("apptainer exec " + " ".join(flags)
                   + " bash -c " + shlex.quote(command))

    if spec.launcher:
        command = spec.launcher + " " + command
    lines.append(command)

    if spec.post_launch:
        lines.append(spec.post_launch)

    lines.append("")
    return "\n".join(lines)


_SUBMIT_RE = re.compile(r"Your job(?:-array)?\s+(\d+)")


def submit(spec: JobSpec) -> dict:
    """Write the rendered script on the cluster and qsub it.

    Returns {job_id, script_path, group} (group is None for a trial run).
    Intentional deviation from IRI's async TaskSubmitResponse: SSH execution is
    synchronous, so qsub returns the job ID directly.
    """
    stamp = time.strftime("%Y%m%d-%H%M%S")
    script_path = write_remote_file(
        f".tsubame/jobs/{spec.name}-{stamp}.sh", render_script(spec)
    )
    # account None -> fall back to the configured default group; account ""
    # (explicit empty) -> force a free trial run (no -g); account "grp" -> that group.
    acct = spec.attributes.account
    group = config.default_group() if acct is None else (acct or None)
    g = f"-g {shlex.quote(group)} " if group else ""  # no -g => free trial run
    output = run_command(f"qsub {g}{shlex.quote(script_path)}")
    # e.g. 'Your job 307 ("sample.sh") has been submitted'
    match = _SUBMIT_RE.search(output)
    if not match:
        raise RuntimeError(f"qsub failed: {output.strip()}")
    return {"job_id": match.group(1), "script_path": script_path, "group": group}


# --- status: qstat (live) + qacct (finished) --------------------------------

def _parse_qstat_line(line: str) -> Job | None:
    """Parse one plain-`qstat` data row into a Job.

    Columns (this AGE build has no `qstat -xml`): job-ID, prior, name, user,
    state, submit/start date, submit/start time, [queue], [jclass], slots,
    [ja-task-ID]. Pending (qw) rows omit queue/jclass, so anchor from the front
    (fixed first five columns + the two-token datetime) and pick the queue and
    slots out of whatever trails: the first non-integer token is the queue, the
    first integer token is the slot count.
    """
    tokens = line.split()
    if len(tokens) < 8 or not tokens[0].isdigit():
        return None  # header ("job-ID ..."), separator ("----"), or blank
    jid, prior, name, user, native = tokens[:5]
    start = f"{tokens[5]} {tokens[6]}"
    queue = ""
    slots = ""
    for tok in tokens[7:]:
        if tok.isdigit():
            slots = tok
            break
        if not queue:
            queue = tok
    return Job(
        id=jid,
        status=JobStatus(
            state=map_ge_state(native),
            meta_data={
                "native_state": native,
                "name": name,
                "user": user,
                "queue": queue,
                "slots": slots,
                "start_time": start,
                "priority": prior,
            },
        ),
    )


def _qstat_jobs() -> dict[str, Job]:
    """All of the current user's live (queued/running) jobs, keyed by job id."""
    output = run_command("qstat")
    jobs: dict[str, Job] = {}
    for line in output.splitlines():
        job = _parse_qstat_line(line)
        if job:
            jobs[job.id] = job
    return jobs


def _parse_epoch(s: str) -> float | None:
    """Parse a qacct time string (e.g. 'Wed Feb 12 17:48:10 2025') to epoch."""
    s = s.strip()
    if not s or s in ("-/-", "undefined"):
        return None
    for fmt in ("%a %b %d %H:%M:%S %Y", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
        try:
            return time.mktime(time.strptime(s, fmt))
        except ValueError:
            continue
    return None


def _qacct_job(job_id: str) -> Job | None:
    """Terminal status of a finished job from `qacct -j <id>`, or None if absent."""
    try:
        output = run_command(f"qacct -j {shlex.quote(job_id)}")
    except RuntimeError:
        return None  # qacct exits non-zero when the job id is unknown
    if not output.strip() or "error:" in output.lower():
        return None
    fields: dict[str, str] = {}
    for line in output.splitlines():
        if line.startswith("=="):
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            fields.setdefault(parts[0], parts[1].strip())  # first record wins
    if not fields:
        return None
    state = map_ge_final_state(fields.get("failed", "0"), fields.get("exit_status", "0"))
    end = _parse_epoch(fields.get("end_time", ""))
    start = _parse_epoch(fields.get("start_time", ""))
    exit_code = None
    try:
        exit_code = int(fields.get("exit_status", "").split()[0])
    except (ValueError, IndexError):
        pass
    return Job(
        id=job_id,
        status=JobStatus(
            state=state,
            time=end or start,
            message=(fields.get("failed") if fields.get("failed", "0").split()[0] != "0" else None),
            exit_code=exit_code,
            meta_data={
                "native_state": "finished",
                "name": fields.get("jobname"),
                "queue": fields.get("qname"),
                "slots": fields.get("slots"),
                "granted_pe": fields.get("granted_pe"),
                "hostname": fields.get("hostname"),
                "start_time": fields.get("start_time"),
                "end_time": fields.get("end_time"),
                "wallclock": fields.get("ru_wallclock"),
                "failed": fields.get("failed"),
            },
        ),
    )


def get_statuses(job_ids: list[str]) -> list[Job]:
    """Fetch normalized statuses for one or more jobs (live via qstat, else qacct)."""
    live = _qstat_jobs()
    result = []
    for jid in job_ids:
        base = jid.split(".")[0]  # strip array task suffix
        if base in live:
            result.append(live[base])
            continue
        finished = _qacct_job(base)
        result.append(finished or Job(
            id=jid,
            status=JobStatus(state=JobState.UNKNOWN,
                             message="not found in qstat or qacct"),
        ))
    return result


def get_recent_statuses() -> list[Job]:
    """The current user's live jobs (queued + running).

    Completed jobs leave qstat immediately on Grid Engine; look one up by id with
    get_statuses (which falls back to qacct) for post-mortem detail.
    """
    return list(_qstat_jobs().values())


def cancel(job_id: str) -> Job | str:
    """qdel, then report the job's resulting state."""
    run_command(f"qdel {shlex.quote(job_id)}")
    jobs = get_statuses([job_id])
    return jobs[0] if jobs else f"qdel sent; job {job_id} not found"
