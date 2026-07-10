"""TSUBAME4 scheduler backend: Altair Grid Engine, sized by RESOURCE TYPE.

TSUBAME4's dialect doesn't fit hpc_agent_core's ready-made GridEngineBackend:
that backend (and cell2026's port of it) models a machine where jobs are
sized by node/slot count (`-pe smp N`), with one real queue and host pins.
TSUBAME4 instead sizes every job by RESOURCE TYPE — `-l node_f=2`, `-l
gpu_1=1`, `-l cpu_40=4`, ... — where the type fixes cores/memory/GPUs/scratch
outright (closer to PBS's `-l nodes=1:ppn=4` than anything core models). Per
PORTING.md §6's explicit guidance for a dialect that doesn't fit either
ready-made backend, this is a full local `TsubameBackend(SchedulerBackend)`
subclass, reusing only the scheduler-neutral helpers
(`duration_to_hms`/`to_epoch`/`parse_exit_code`) from
`hpc_agent_core.compute.base` — `render_body` is not reusable either: it
hardcodes `singularity exec`, while TSUBAME4 provides Apptainer and needs
extra site bind mounts (`/gs`, `/apps`, `/home`), so the body is rendered
locally too.

Every other TSUBAME4-specific field that pre-migration lived on a custom
`ResourceSpec`/`JobAttributes` (resource_type, resource_count, priority,
array, hold_jid, gpu_compute_mode) is carried through core's SHARED,
machine-agnostic models instead of a core edit (machines have no write
access to hpc_agent_core.models) — deliberately mapped as follows:

  resource_type    -> attributes.custom_attributes["resource_type"] (default "node_f")
  resource_count   -> resources.node_count (PSI/J's "how many of the primary
                      allocation unit" already means the same thing here)
  priority         -> attributes.custom_attributes["priority"] (default "-5")
  array            -> attributes.custom_attributes.get("array")
  hold_jid         -> attributes.custom_attributes.get("hold_jid")
  gpu_compute_mode -> attributes.custom_attributes.get("gpu_compute_mode")
  queue_name       -> attributes.queue_name (core field, same purpose: -q)
  reservation_id   -> attributes.reservation_id (core field, same purpose: -ar)
  account          -> attributes.account (core field; already matches TSUBAME's
                      tri-state semantics exactly: None -> configured default
                      group, "" -> forced free trial run with no -g, "<group>"
                      -> that group — nothing TSUBAME-specific needed here)
  duration         -> attributes.duration (core field, matches h_rt)
  inherit_environment -> spec.inherit_environment (core field, matches -V)
  cpu_cores_per_process -> resources.cpu_cores_per_process (core field, used
                      for the OMP_NUM_THREADS export, same as pre-migration)
  processes_per_node -> resources.processes_per_node (core field, launch-line
                      only, not a scheduler flag, same as pre-migration)

`custom_attributes` (a `dict[str, str]` already on core's JobAttributes) is
the intended escape valve for exactly this kind of machine-specific
extension — this is not a workaround, it's the sanctioned use of that field.
"""
import re
import shlex
import time

from hpc_agent_core.compute.base import SchedulerBackend, duration_to_hms, parse_exit_code, to_epoch
from hpc_agent_core.middleware import run_command, write_remote_file
from hpc_agent_core.models import Job, JobSpec, JobState, JobStatus
from tsubame_mcp import config  # noqa: F401 -- registers via configure(); this
# module must not rely on being imported after config by whoever imports it.

_DEFAULT_RESOURCE_TYPE = "node_f"
_DEFAULT_PRIORITY = "-5"

# Grid Engine `qstat` state codes (single- or multi-letter). Finished jobs no
# longer appear in qstat — their terminal state comes from qacct (see
# _final_state below). NOT hpc_agent_core.models.map_ge_state: that's a
# stricter dict-only lookup (no fallback) covering the subset of codes
# cell2026's AGE deployment has actually produced; this AGE deployment's own
# pre-migration state table is richer (hRwq, Rq, plain h/T/d/E) and has a
# substring-based fallback for any code not explicitly listed — using core's
# version verbatim would silently misreport real states as UNKNOWN, so this
# mapping stays local rather than being forced through the shared one.
_GE_STATE_MAP = {
    "qw": JobState.QUEUED,     # queued, waiting
    "hqw": JobState.HELD,      # queued and held
    "hRwq": JobState.HELD,     # held, rescheduled, waiting
    "Rq": JobState.QUEUED,     # rescheduled, waiting to run
    "r": JobState.ACTIVE,      # running
    "t": JobState.ACTIVE,      # transferring (job start)
    "Rr": JobState.ACTIVE,     # rescheduled and running
    "h": JobState.HELD,        # on hold
    "s": JobState.HELD,        # suspended
    "S": JobState.HELD,        # suspended by the queue
    "T": JobState.HELD,        # suspended (threshold reached)
    "d": JobState.CANCELED,    # being deleted
    "dr": JobState.CANCELED,   # being deleted while running
    "E": JobState.FAILED,      # error
    "Eqw": JobState.FAILED,    # error while pending
}


def _map_ge_state(native: str) -> JobState:
    """Map a `qstat` state code to a normalized JobState.

    Codes combine letters (e.g. 'hqw', 'dr'); try the whole token, then fall
    back to the primary run/queue letter so unknown combinations still resolve.
    """
    native = native.strip()
    if native in _GE_STATE_MAP:
        return _GE_STATE_MAP[native]
    if "E" in native:
        return JobState.FAILED
    if "d" in native:
        return JobState.CANCELED
    if "r" in native or "t" in native:
        return JobState.ACTIVE
    if "h" in native or "s" in native or "S" in native or "T" in native:
        return JobState.HELD
    if "q" in native:
        return JobState.QUEUED
    return JobState.UNKNOWN


def _resource_type(spec: JobSpec) -> str:
    return spec.attributes.custom_attributes.get("resource_type", _DEFAULT_RESOURCE_TYPE)


def _has_gpus(resource_type: str) -> bool:
    """Whether resource_type provides GPUs, from the bundled resource-type
    table (the single source of truth — not duplicated as a second local
    constant)."""
    for rt in config.load_cluster_config().get("resource_types", []):
        if rt["name"] == resource_type:
            return bool(rt.get("gpus"))
    return False


def _final_state(failed: str, exit_status: str) -> JobState:
    """Terminal state for a finished job from qacct `failed` / `exit_status`.

    `failed` is 0 when the job ran to completion (non-zero = scheduler/
    runtime failure, e.g. wall-clock exceeded); `exit_status` is the
    program's exit code. Either being non-zero means the job did not
    succeed. (Not the same thing map_ge_state covers — that's for qstat's
    live-job state letters, not qacct's finished-job fields — so this stays
    local rather than trying to force it through map_ge_state.)
    """
    try:
        failed_n = int(str(failed).split()[0])
    except (ValueError, IndexError):
        failed_n = 0
    try:
        exit_n = int(str(exit_status).split()[0])
    except (ValueError, IndexError):
        exit_n = 0
    if failed_n != 0 or exit_n != 0:
        return JobState.FAILED
    return JobState.COMPLETED


class TsubameBackend(SchedulerBackend):
    name = "tsubame-ge"

    def _header(self, spec: JobSpec) -> list[str]:
        res = spec.resources
        attr = spec.attributes
        resource_type = _resource_type(spec)
        priority = attr.custom_attributes.get("priority", _DEFAULT_PRIORITY)

        lines = ["#!/bin/sh"]
        # Working directory: -cwd runs in the submit dir; -wd sets an explicit one.
        if spec.directory:
            lines.append(f"#$ -wd {shlex.quote(spec.directory)}")
        else:
            lines.append("#$ -cwd")

        lines.append(f"#$ -l {resource_type}={res.node_count}")
        lines.append(f"#$ -l h_rt={duration_to_hms(attr.duration)}")
        lines.append(f"#$ -N {shlex.quote(spec.name)}")
        lines.append(f"#$ -p {priority}")

        if attr.queue_name:
            lines.append(f"#$ -q {shlex.quote(attr.queue_name)}")
        if "array" in attr.custom_attributes:
            lines.append(f"#$ -t {attr.custom_attributes['array']}")
        if "hold_jid" in attr.custom_attributes:
            lines.append(f"#$ -hold_jid {shlex.quote(attr.custom_attributes['hold_jid'])}")
        if attr.reservation_id:
            lines.append(f"#$ -ar {shlex.quote(attr.reservation_id)}")
        if spec.stdout_path:
            lines.append(f"#$ -o {shlex.quote(spec.stdout_path)}")
        if spec.stderr_path:
            lines.append(f"#$ -e {shlex.quote(spec.stderr_path)}")
        if spec.inherit_environment:
            # -V forwards the submission environment. TSUBAME4 caveat: with
            # -V, module load can misbehave, so scripts should `module
            # purge` first (pre_launch) — and LD_LIBRARY_PATH/LD_PRELOAD are
            # never forwarded.
            lines.append("#$ -V")
        # GPU compute mode is a job-level environment variable consumed by
        # the site prolog; only valid for node_f/node_h/node_q/gpu_1.
        if "gpu_compute_mode" in attr.custom_attributes:
            lines.append(f"#$ -v GPU_COMPUTE_MODE={int(attr.custom_attributes['gpu_compute_mode'])}")

        for key, val in attr.custom_attributes.items():
            if key in ("resource_type", "priority", "array", "hold_jid", "gpu_compute_mode"):
                continue  # already handled above via their dedicated fields
            lines.append(f"#$ -{key} {val}")

        return lines

    def _body(self, spec: JobSpec) -> str:
        """The scheduler-neutral body: env exports, pre_launch, the
        command (optionally apptainer-wrapped), launcher, post_launch.

        Not core's render_body: that hardcodes `singularity exec` with no
        site bind mounts, whereas TSUBAME4 provides Apptainer and always
        bind-mounts /gs, /apps, /home.
        """
        res = spec.resources
        lines: list[str] = [""]  # blank line after headers

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
            # TSUBAME4 provides Apptainer; wrap in `apptainer exec`,
            # bind-mounting site storage and enabling GPUs when the
            # resource type provides them.
            c = spec.container
            flags = ["-B", "/gs", "-B", "/apps", "-B", "/home"]
            if _has_gpus(_resource_type(spec)):
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

    def render_script(self, spec: JobSpec) -> str:
        """Render a JobSpec as a TSUBAME4 Grid Engine job script.

        The `-g` group is a qsub command-line argument (not a script
        directive, per the User's Guide) and is added in submit(), not here.
        """
        return "\n".join(self._header(spec)) + self._body(spec)

    _SUBMIT_RE = re.compile(r"Your job(?:-array)?\s+(\d+)")

    def submit(self, spec: JobSpec) -> dict:
        """Write the rendered script on the cluster and qsub it.

        Returns {job_id, script_path, group} (group is None for a trial
        run). Intentional deviation from IRI's async TaskSubmitResponse:
        SSH execution is synchronous, so qsub returns the job ID directly.
        """
        stamp = time.strftime("%Y%m%d-%H%M%S")
        script_path = write_remote_file(
            f"agent/jobs/{spec.name}-{stamp}.sh", self.render_script(spec)
        )
        # account None -> fall back to the configured default group; account
        # "" (explicit empty) -> force a free trial run (no -g); account
        # "grp" -> that group.
        acct = spec.attributes.account
        group = config.default_group() if acct is None else (acct or None)
        g = f"-g {shlex.quote(group)} " if group else ""  # no -g => free trial run
        output = run_command(f"qsub {g}{shlex.quote(script_path)}")
        # e.g. 'Your job 307 ("sample.sh") has been submitted'
        match = self._SUBMIT_RE.search(output)
        if not match:
            raise RuntimeError(f"qsub failed: {output.strip()}")
        return {"job_id": match.group(1), "script_path": script_path, "group": group}

    # --- status: qstat (live) + qacct (finished) ----------------------------

    @staticmethod
    def _parse_qstat_line(line: str) -> Job | None:
        """Parse one plain-`qstat` data row into a Job.

        Columns (this AGE build has no `qstat -xml`): job-ID, prior, name,
        user, state, submit/start date, submit/start time, [queue],
        [jclass], slots, [ja-task-ID]. Pending (qw) rows omit queue/jclass,
        so anchor from the front (fixed first five columns + the two-token
        datetime) and pick the queue and slots out of whatever trails: the
        first non-integer token is the queue, the first integer token is
        the slot count.
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
                state=_map_ge_state(native),
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

    def _qstat_jobs(self) -> dict[str, Job]:
        """All of the current user's live (queued/running) jobs, keyed by job id."""
        output = run_command("qstat")
        jobs: dict[str, Job] = {}
        for line in output.splitlines():
            job = self._parse_qstat_line(line)
            if job:
                jobs[job.id] = job
        return jobs

    @staticmethod
    def _parse_qacct_epoch(s: str) -> float | None:
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

    def _qacct_job(self, job_id: str) -> Job | None:
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
        state = _final_state(fields.get("failed", "0"), fields.get("exit_status", "0"))
        end = self._parse_qacct_epoch(fields.get("end_time", ""))
        start = self._parse_qacct_epoch(fields.get("start_time", ""))
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

    def get_statuses(self, job_ids: list[str]) -> list[Job]:
        """Fetch normalized statuses for one or more jobs (live via qstat, else qacct)."""
        live = self._qstat_jobs()
        result = []
        for jid in job_ids:
            base = jid.split(".")[0]  # strip array task suffix
            if base in live:
                result.append(live[base])
                continue
            finished = self._qacct_job(base)
            result.append(finished or Job(
                id=jid,
                status=JobStatus(state=JobState.UNKNOWN,
                                 message="not found in qstat or qacct"),
            ))
        return result

    def get_recent_statuses(self, since: str = "now-2days") -> list[Job]:
        """The current user's live jobs (queued + running).

        Completed jobs leave qstat immediately on Grid Engine; look one up
        by id with get_statuses (which falls back to qacct) for
        post-mortem detail. `since` is accepted for interface parity with
        other backends but ignored — there is no history to window over.
        """
        return list(self._qstat_jobs().values())

    def cancel(self, job_id: str) -> Job | str:
        """qdel, then report the job's resulting state."""
        run_command(f"qdel {shlex.quote(job_id)}")
        jobs = self.get_statuses([job_id])
        return jobs[0] if jobs else f"qdel sent; job {job_id} not found"


backend = TsubameBackend()

# hpc_server.py calls these:
render_script = backend.render_script
submit = backend.submit
get_statuses = backend.get_statuses
get_recent_statuses = backend.get_recent_statuses
cancel = backend.cancel
