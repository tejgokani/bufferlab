"""Run one experiment through the simulator."""

from __future__ import annotations

import threading

from bufferlab.algorithms import build_queue_manager
from bufferlab.core.simulator import ProgressCallback, Simulator
from bufferlab.experiments.models import (
    ConfigError,
    ExperimentConfig,
    RunRecord,
    new_run_id,
    utc_now,
)
from bufferlab.utils.logging import get_logger, log_event


def run_experiment(
    config: ExperimentConfig,
    on_progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
    *,
    batch_id: str | None = None,
    replicate: int = 0,
) -> RunRecord:
    """Validate and execute ``config``; returns an (unsaved) :class:`RunRecord`."""
    report = config.validate()
    if not report.ok:
        raise ConfigError(report)
    sim_cfg = config.to_sim_config()
    qm = build_queue_manager(
        config.algorithm,
        config.queue_capacity,
        config.algorithm_params,
        service_time=config.packet_size_bytes * 8 / sim_cfg.capacity_bps,
        mtu_bytes=config.packet_size_bytes,
        seed=config.seed,
    )
    result = Simulator(sim_cfg, qm, on_progress=on_progress, cancel=cancel).run()
    record = RunRecord(
        run_id=new_run_id(),
        created_at=utc_now(),
        config=config,
        resolved_params=config.resolved_params(),
        metrics=result.metrics.to_dict(),
        series=result.series,
        terminated=result.terminated,
        events_processed=result.events_processed,
        wall_time_s=result.wall_time_s,
        batch_id=batch_id,
        replicate=replicate,
    )
    log_event(
        get_logger(),
        "run complete",
        run_id=record.run_id,
        algorithm=config.algorithm,
        seed=config.seed,
        terminated=result.terminated,
        events=result.events_processed,
    )
    return record
