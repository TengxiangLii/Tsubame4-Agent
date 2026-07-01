"""Data models mirroring the IRI Facility API schemas.

The IRI (Integrated Research Infrastructure) Facility API is the DOE standard
for programmatic facility access (spec at api.alcf.anl.gov/openapi.json). Its
compute schemas follow PSI/J: a JobSpec with ResourceSpec + JobAttributes, and a
normalized JobState. We implement a pragmatic subset; deviations are noted in
IRI_CHECKLIST.md at the repository root.

TSUBAME4.0 is a GPU-first system: 240 nodes, each with 2x AMD EPYC 9654 (192
cores) and 4x NVIDIA H100. Crucially, jobs are sized in *resource-type units*
(`-l node_f=2`, `gpu_1`, `cpu_4`, ...), not the Slurm nodes/ntasks/cpus that the
PSI/J ResourceSpec assumes — so ResourceSpec here carries `resource_type` +
`resource_count` (a documented deviation, like PBS's `-l nodes=1:ppn=4`). The
scheduler is Altair Grid Engine, so states map from `qstat`/`qacct`, not sacct.
"""
from enum import Enum

from pydantic import BaseModel, Field


class JobState(str, Enum):
    """Normalized job states (IRI/PSI-J), mapped from Grid Engine states."""
    NEW = "new"
    QUEUED = "queued"
    HELD = "held"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    UNKNOWN = "unknown"


# Grid Engine `qstat` state codes (single- or multi-letter). Finished jobs no
# longer appear in qstat — their terminal state comes from qacct (see
# map_ge_final_state).
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


def map_ge_state(native: str) -> JobState:
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


def map_ge_final_state(failed: str, exit_status: str) -> JobState:
    """Terminal state for a finished job from qacct `failed` / `exit_status`.

    `failed` is 0 when the job ran to completion (non-zero = scheduler/runtime
    failure, e.g. wall-clock exceeded); `exit_status` is the program's exit code.
    Either being non-zero means the job did not succeed.
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


# The resource types TSUBAME4 exposes (compute nodes are logically divided).
# GPU count is informational; the scheduler derives cores/mem/GPUs from the type.
RESOURCE_TYPES = {
    "node_f":  {"cores": 192, "mem_gb": 768, "gpus": 4,   "scratch_gib": 1660},
    "node_h":  {"cores": 96,  "mem_gb": 384, "gpus": 2,   "scratch_gib": 830},
    "node_q":  {"cores": 48,  "mem_gb": 192, "gpus": 1,   "scratch_gib": 415},
    "node_o":  {"cores": 24,  "mem_gb": 96,  "gpus": 0.5, "scratch_gib": 200},
    "gpu_1":   {"cores": 8,   "mem_gb": 96,  "gpus": 1,   "scratch_gib": 200},
    "gpu_h":   {"cores": 4,   "mem_gb": 48,  "gpus": 0.5, "scratch_gib": 100},
    "cpu_160": {"cores": 160, "mem_gb": 368, "gpus": 0,   "scratch_gib": 830},
    "cpu_80":  {"cores": 80,  "mem_gb": 184, "gpus": 0,   "scratch_gib": 415},
    "cpu_40":  {"cores": 40,  "mem_gb": 92,  "gpus": 0,   "scratch_gib": 200},
    "cpu_16":  {"cores": 16,  "mem_gb": 36.8, "gpus": 0,  "scratch_gib": 83},
    "cpu_8":   {"cores": 8,   "mem_gb": 18.4, "gpus": 0,  "scratch_gib": 40},
    "cpu_4":   {"cores": 4,   "mem_gb": 9.2,  "gpus": 0,  "scratch_gib": 20},
}


class ResourceSpec(BaseModel):
    """Resources for a job (PSI/J ResourceSpec adapted to TSUBAME4 resource types).

    TSUBAME4 sizes jobs by resource type: `-l <resource_type>=<resource_count>`
    reserves that many logically-divided units, and each type fixes the cores,
    memory, GPUs and local scratch (see RESOURCE_TYPES). The default is `node_f`
    (a full node: 192 cores + 4x H100) — TSUBAME4 is GPU-first, so the typical
    job takes whole nodes with GPUs.

    processes_per_node and cpu_cores_per_process describe the MPI/OpenMP *launch*
    layout (used to build the mpirun/mpiexec line and OMP_NUM_THREADS); they do
    not become scheduler flags — Grid Engine derives cores from the resource type.
    """
    resource_type: str = Field("node_f", description="Resource type: node_f/node_h/node_q/node_o/gpu_1/gpu_h/cpu_160.../cpu_4")
    resource_count: int = Field(1, description="Number of resource-type units (the =N in -l <type>=N)")
    processes_per_node: int = Field(1, description="MPI ranks per unit — used for the launch line, not a scheduler flag")
    cpu_cores_per_process: int | None = Field(None, description="OpenMP threads per rank — sets OMP_NUM_THREADS / launch layout")
    gpu_compute_mode: int | None = Field(None, description="TSUBAME4 extension: GPU_COMPUTE_MODE (0 DEFAULT, 1 EXCLUSIVE_PROCESS, 2 PROHIBITED) via #$ -v; only node_f/node_h/node_q/gpu_1")


class JobAttributes(BaseModel):
    """Scheduler attributes (IRI/PSI/J JobAttributes subset), for Grid Engine."""
    duration: int | str = Field(
        "1:00:00",
        description="Wall time (h_rt) as integer seconds or [[HH:]MM:]SS string (TSUBAME4 default 1h, max 24h)",
    )
    account: str | None = Field(None, description="TSUBAME group (the qsub -g argument) charged in points. None = use the configured default group; \"\" (empty) = force a free trial run (no -g); \"<group>\" = charge that group.")
    priority: int = Field(-5, description="Execution priority (qsub -p): -5 standard (default), -4 higher, -3 highest (-4/-3 cost more points)")
    queue_name: str | None = Field(None, description="qsub -q; normally unset (Normal queue). Set 'prior' for a compute-node subscription job.")
    reservation_id: str | None = Field(None, description="Reserved node AR ID (qsub -ar)")
    hold_jid: str | None = Field(None, description="Job dependency: run after this job ID finishes (qsub -hold_jid)")
    array: str | None = Field(None, description="Array task range start-end[:step] (qsub -t)")
    custom_attributes: dict[str, str] = Field(default_factory=dict)


class CompressionType(str, Enum):
    """Compression format for fs_compress / fs_extract (IRI CompressionType)."""
    NONE = "none"
    BZIP2 = "bzip2"
    GZIP = "gzip"
    XZ = "xz"


class VolumeMount(BaseModel):
    """A host path mounted into a container (IRI VolumeMount)."""
    source: str = Field(description="Host path to mount")
    target: str = Field(description="Path inside the container")
    read_only: bool = Field(True, description="Mount as read-only")


class Container(BaseModel):
    """Container specification (IRI Container); executed via apptainer exec on TSUBAME4.

    image must be a path to a .sif file / sandbox (absolute or using $HOME), or a
    URI such as docker://ubuntu:latest. The site storage (/gs, /apps, /home) is
    bind-mounted and GPU passthrough (--nv) is added automatically when the
    resource type provides GPUs. launcher (e.g. 'mpirun') is placed outside
    apptainer exec so MPI works.
    """
    image: str = Field(description="Apptainer image path or URI (e.g. docker://ubuntu:latest)")
    volume_mounts: list[VolumeMount] = Field(default_factory=list)


class JobSpec(BaseModel):
    """Job specification (IRI/PSI/J JobSpec subset).

    executable plus arguments form the command run inside the batch script;
    executable may be a shell line (e.g. 'module load cuda && ./a.out').
    launcher, if set, is prepended to executable (e.g. 'mpirun -npernode 8 -n 32').
    pre_launch / post_launch are script lines inserted before / after (module
    loads belong in pre_launch). If container is set, the command is wrapped in
    'apptainer exec'.
    """
    name: str = "tsubame-job"
    executable: str
    arguments: list[str] = Field(default_factory=list)
    directory: str | None = Field(None, description="Working directory for the job (default: submit dir, via #$ -cwd)")
    environment: dict[str, str] = Field(default_factory=dict)
    inherit_environment: bool = Field(True, description="Inherit submission environment variables (qsub -V; note TSUBAME4 cannot pass LD_LIBRARY_PATH/LD_PRELOAD)")
    stdout_path: str | None = None
    stderr_path: str | None = None
    resources: ResourceSpec = Field(default_factory=ResourceSpec)
    attributes: JobAttributes = Field(default_factory=JobAttributes)
    pre_launch: str | None = Field(None, description="Script lines to insert before executable (e.g. 'module purge && module load cuda')")
    post_launch: str | None = Field(None, description="Script lines to insert after executable")
    launcher: str | None = Field(None, description="Launcher prefix, e.g. 'mpirun -npernode 8 -n 32' or 'mpiexec.hydra -ppn 8 -n 32'")
    container: Container | None = Field(None, description="Run inside an Apptainer container")


class JobStatus(BaseModel):
    """IRI-compliant job status (state + time + message + exit_code + meta_data).

    Grid-Engine-specific detail (native_state, queue, slots, workdir, elapsed,
    start/end times) is carried in meta_data.
    """
    state: JobState
    time: float | None = Field(None, description="Epoch seconds: end_time if finished, start_time if running")
    message: str | None = Field(None, description="Human-readable status (queue reason, error, etc.)")
    exit_code: int | None = None
    meta_data: dict | None = Field(None, description="Grid-Engine-specific fields: native_state, queue, slots, workdir, elapsed, etc.")


class Job(BaseModel):
    """IRI Job: identifier + current status + originating spec."""
    id: str
    status: JobStatus | None = None
    job_spec: JobSpec | None = None
