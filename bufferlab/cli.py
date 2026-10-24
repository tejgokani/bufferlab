"""Command-line interface.  ``bufferlab`` with no sub-command opens the TUI."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from bufferlab import __version__
from bufferlab.algorithms import ALGORITHMS, algorithm_keys
from bufferlab.analysis.comparison import COLUMNS, comparison_rows, fmt_value, observations
from bufferlab.analysis.reporting import FORMATS, export_runs
from bufferlab.core.traffic import TRAFFIC_MODELS
from bufferlab.experiments.models import ExperimentConfig, RunRecord
from bufferlab.experiments.runner import run_experiment
from bufferlab.experiments.scenarios import SCENARIOS, scenario_config
from bufferlab.storage import AmbiguousIdError, NotFoundError, Repository
from bufferlab.utils.paths import db_path, exports_dir

app = typer.Typer(
    help="BufferLab: simulate and compare network queue-management algorithms.",
    no_args_is_help=False,
    add_completion=False,
    rich_markup_mode=None,
)
console = Console()
err = Console(stderr=True)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"bufferlab {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version, is_eager=True, help="Show version and exit."),
    ] = False,
) -> None:
    if ctx.invoked_subcommand is None:
        from bufferlab.tui.app import run_tui

        run_tui()


def _fail(msg: str, code: int = 2) -> None:
    err.print(f"[red]error:[/red] {msg}", markup=True)
    raise typer.Exit(code)


def _parse_scalar(text: str) -> Any:
    low = text.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text.strip()


def _parse_params(items: list[str] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            _fail(f"--param expects key=value, got {item!r}")
        k, v = item.split("=", 1)
        out[k.strip()] = _parse_scalar(v)
    return out


def _repo() -> Repository:
    return Repository()


def _metrics_table(rec: RunRecord) -> Table:
    m = rec.metrics
    t = Table(title=f"{rec.run_id}  {rec.config.algorithm}  ({rec.config.name})", show_header=False)
    t.add_column(style="cyan")
    t.add_column(justify="right")

    def f(v: Any, d: int = 3, suffix: str = "") -> str:
        return "n/a" if v is None else f"{v:.{d}f}{suffix}"

    rows = [
        (
            "Offered load",
            f"{m['offered_load_mbps']:.3f} Mbps ({m['offered_load_pct']:.1f}% of link)",
        ),
        ("Delivered throughput", f(m["throughput_mbps"], 3, " Mbps")),
        (
            "Packet delivery ratio",
            f(None if m["delivery_ratio"] is None else m["delivery_ratio"] * 100, 2, "%"),
        ),
        ("Packet loss rate", f(None if m["loss_rate"] is None else m["loss_rate"] * 100, 2, "%")),
        (
            "Generated / delivered / dropped / unresolved",
            f"{m['generated']:,} / {m['delivered']:,} / {m['dropped']:,} / {m['unresolved']:,}",
        ),
        (
            "Drops: overflow / early / AQM",
            f"{m['dropped_overflow']:,} / {m['dropped_early']:,} / {m['dropped_aqm']:,}",
        ),
        (
            "Queueing delay avg / median / p95 / max",
            " / ".join(
                f(m[k], 2)
                for k in (
                    "avg_queue_delay_ms",
                    "median_queue_delay_ms",
                    "p95_queue_delay_ms",
                    "max_queue_delay_ms",
                )
            )
            + " ms",
        ),
        (
            "Queue occupancy avg / max (pkts)",
            f"{m['avg_queue_len']:.2f} / {m['max_queue_len']} (capacity {rec.config.queue_capacity})",
        ),
        ("Queue utilisation", f"{m['queue_utilisation'] * 100:.1f}%"),
        ("Link utilisation", f"{m['link_utilisation'] * 100:.1f}%"),
        ("Overflow events", f"{m['overflow_events']:,}"),
        (
            "Status",
            f"{rec.terminated}; {rec.events_processed:,} events in {rec.wall_time_s:.2f}s wall",
        ),
    ]
    for k, v in rows:
        t.add_row(k, v)
    return t


def _comparison_table(runs: list[RunRecord]) -> Table:
    t = Table(title="Run comparison")
    t.add_column("Tag")
    t.add_column("Run ID", style="cyan")
    t.add_column("Algorithm")
    for c in COLUMNS:
        t.add_column(f"{c.label} ({c.unit})", justify="right")
    for row in comparison_rows(runs):
        t.add_row(
            row["tag"],
            row["run_id"],
            row["algorithm"],
            *[fmt_value(c, row[c.key]) for c in COLUMNS],
        )
    return t


def _resolve_runs(repo: Repository, refs: list[str]) -> list[RunRecord]:
    try:
        return [repo.get_run(r) for r in refs]
    except (NotFoundError, AmbiguousIdError) as e:
        _fail(str(e), 1)
        raise  # unreachable


# -- commands --------------------------------------------------------------------
@app.command("scenarios")
def scenarios_cmd() -> None:
    """List built-in scenarios and their parameters."""
    t = Table(title="Scenarios")
    for col in ("Key", "Link", "Load", "Buffer", "Traffic", "Duration", "Description"):
        t.add_column(col, no_wrap=col in ("Key", "Link", "Load"))
    for s in SCENARIOS.values():
        c = s.config
        t.add_row(
            s.key,
            f"{c.link_mbps:g} Mbps",
            f"{c.offered_load_pct:g}%",
            f"{c.queue_capacity} pkts",
            f"{c.traffic_model} x{c.n_sources}",
            f"{c.duration_s:g}s (+{c.warmup_s:g}s warm-up)",
            s.description,
        )
    console.print(t)


@app.command("algorithms")
def algorithms_cmd() -> None:
    """List algorithms and their parameters."""
    for spec in ALGORITHMS.values():
        console.print(f"[bold cyan]{spec.key}[/bold cyan]  {spec.summary}")
        for p in spec.params:
            d = p.auto_hint or p.default
            console.print(f"    {p.name:<12} default {d}  {p.unit}  {p.help}")


def _build_config(
    scenario: str,
    algorithm: str,
    name: str | None,
    load: float | None,
    capacity: int | None,
    bandwidth: float | None,
    packet_size: int | None,
    traffic: str | None,
    sources: int | None,
    duration: float | None,
    warmup: float | None,
    seed: int | None,
    prop_delay: float | None,
    param: list[str] | None,
    max_events: int | None,
) -> ExperimentConfig:
    if algorithm not in algorithm_keys():
        _fail(f"unknown algorithm {algorithm!r}; choose from {', '.join(algorithm_keys())}")
    over: dict[str, Any] = {}
    for k, v in (
        ("offered_load_pct", load),
        ("queue_capacity", capacity),
        ("link_mbps", bandwidth),
        ("packet_size_bytes", packet_size),
        ("traffic_model", traffic),
        ("n_sources", sources),
        ("duration_s", duration),
        ("warmup_s", warmup),
        ("seed", seed),
        ("prop_delay_ms", prop_delay),
        ("max_events", max_events),
        ("name", name),
    ):
        if v is not None:
            over[k] = v
    over["algorithm_params"] = _parse_params(param)
    try:
        return scenario_config(scenario, algorithm, **over)
    except ValueError as e:
        _fail(str(e))
        raise


@app.command("run")
def run_cmd(
    scenario: Annotated[
        str, typer.Option("--scenario", "-s", help="Scenario key (see `scenarios`).")
    ] = "approaching-saturation",
    algorithm: Annotated[
        str, typer.Option("--algorithm", "-a", help="drop-tail | red | codel")
    ] = "drop-tail",
    name: Annotated[str | None, typer.Option(help="Experiment name.")] = None,
    load: Annotated[float | None, typer.Option(help="Offered load, % of link capacity.")] = None,
    capacity: Annotated[int | None, typer.Option(help="Queue capacity (packets).")] = None,
    bandwidth: Annotated[float | None, typer.Option(help="Link bandwidth (Mbps).")] = None,
    packet_size: Annotated[int | None, typer.Option(help="Packet size (bytes).")] = None,
    traffic: Annotated[
        str | None, typer.Option(help=f"Traffic model: {', '.join(TRAFFIC_MODELS)}")
    ] = None,
    sources: Annotated[int | None, typer.Option(help="Number of traffic sources.")] = None,
    duration: Annotated[float | None, typer.Option(help="Simulated seconds.")] = None,
    warmup: Annotated[
        float | None, typer.Option(help="Warm-up seconds (excluded from metrics).")
    ] = None,
    seed: Annotated[int | None, typer.Option(help="Random seed.")] = None,
    prop_delay: Annotated[
        float | None, typer.Option(help="One-way propagation delay (ms).")
    ] = None,
    max_events: Annotated[int | None, typer.Option(help="Event limit.")] = None,
    param: Annotated[
        list[str] | None,
        typer.Option("--param", "-p", help="Algorithm parameter key=value (repeatable)."),
    ] = None,
    no_save: Annotated[bool, typer.Option("--no-save", help="Do not store the result.")] = False,
) -> None:
    """Run one experiment without opening the TUI."""
    cfg = _build_config(
        scenario,
        algorithm,
        name,
        load,
        capacity,
        bandwidth,
        packet_size,
        traffic,
        sources,
        duration,
        warmup,
        seed,
        prop_delay,
        param,
        max_events,
    )
    report = cfg.validate()
    for w in report.warnings:
        err.print(f"[yellow]warning:[/yellow] {w.field}: {w.message}")
    if not report.ok:
        for e in report.errors:
            err.print(f"[red]error:[/red] {e.field}: {e.message}")
        raise typer.Exit(2)
    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=err,
        transient=True,
    ) as prog:
        task = prog.add_task(f"simulating {cfg.algorithm}", total=1.0)
        rec = run_experiment(cfg, on_progress=lambda p: prog.update(task, completed=p.fraction))
    if not no_save:
        _repo().save_run(rec)
    console.print(_metrics_table(rec))
    if rec.terminated != "completed":
        err.print(
            f"[yellow]warning:[/yellow] run ended early ({rec.terminated}); metrics cover the simulated portion only"
        )
    if not no_save:
        console.print(f"saved as [cyan]{rec.run_id}[/cyan]")


@app.command("history")
def history_cmd(
    search: Annotated[
        str | None, typer.Option("--search", "-q", help="Filter by id/name/scenario/algorithm.")
    ] = None,
    algorithm: Annotated[str | None, typer.Option("--algorithm", "-a")] = None,
    limit: Annotated[int, typer.Option()] = 30,
) -> None:
    """List saved experiments (newest first)."""
    runs = _repo().list_runs(search=search, algorithm=algorithm, limit=limit)
    if not runs:
        console.print(
            "No saved experiments. Try: bufferlab run --scenario heavy-congestion --algorithm codel"
        )
        return
    t = Table(title=f"Experiment history ({db_path()})")
    for col in (
        "Run ID",
        "When (UTC)",
        "Name",
        "Algorithm",
        "Seed",
        "Thr Mbps",
        "Loss %",
        "p95 ms",
        "Batch",
    ):
        t.add_column(col, no_wrap=col in ("Run ID", "Batch", "Algorithm"))
    for r in runs:
        m = r.metrics
        t.add_row(
            r.run_id,
            r.created_at.replace("T", " ")[:19],
            r.config.name,
            r.config.algorithm,
            str(r.config.seed),
            f"{m['throughput_mbps']:.2f}",
            "n/a" if m["loss_rate"] is None else f"{m['loss_rate'] * 100:.2f}",
            "n/a" if m["p95_queue_delay_ms"] is None else f"{m['p95_queue_delay_ms']:.2f}",
            r.batch_id or "",
        )
    console.print(t)


@app.command("show")
def show_cmd(run_id: str) -> None:
    """Show one saved run's configuration and metrics."""
    rec = _resolve_runs(_repo(), [run_id])[0]
    console.print("\n".join(rec.config.summary_lines()))
    console.print(_metrics_table(rec))


@app.command("compare")
def compare_cmd(run_ids: Annotated[list[str], typer.Argument(help="Two or more run IDs.")]) -> None:
    """Compare completed runs side by side."""
    if len(run_ids) < 2:
        _fail("give at least two run IDs")
    runs = _resolve_runs(_repo(), run_ids)
    console.print(_comparison_table(runs))
    console.print("[bold]Observations[/bold] (automated, from measured values)")
    for o in observations(runs):
        console.print(f"  - {o}")


@app.command("export")
def export_cmd(
    run_ids: Annotated[list[str] | None, typer.Argument(help="Run IDs to export.")] = None,
    fmt: Annotated[str, typer.Option("--format", "-f", help=f"{', '.join(FORMATS)}")] = "csv",
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
) -> None:
    """Export runs to CSV, JSON, Markdown or text."""
    if fmt not in FORMATS:
        _fail(f"unsupported format {fmt!r}; choose from {', '.join(FORMATS)}")
    repo = _repo()
    if not run_ids:
        _fail("give one or more RUN_IDs")
    runs = [repo.get_run(r) for r in _resolve_ids(repo, run_ids)]
    out = output or exports_dir() / (
        f"{runs[0].run_id}.{fmt}" if len(runs) == 1 else f"runs-{len(runs)}.{fmt}"
    )
    console.print(f"wrote {export_runs(runs, fmt, out)}")


def _resolve_ids(repo: Repository, refs: list[str]) -> list[str]:
    try:
        return [repo.resolve_id(r) for r in refs]
    except (NotFoundError, AmbiguousIdError) as e:
        _fail(str(e), 1)
        raise


@app.command("rerun")
def rerun_cmd(
    run_id: str,
    new_seed: Annotated[
        int | None,
        typer.Option(help="Use a different seed (default: same seed => identical result)."),
    ] = None,
) -> None:
    """Re-execute a saved run's configuration."""
    repo = _repo()
    old = _resolve_runs(repo, [run_id])[0]
    cfg = old.config if new_seed is None else old.config.replace(seed=new_seed)
    rec = run_experiment(cfg)
    repo.save_run(rec)
    console.print(_metrics_table(rec))
    same = rec.metrics == old.metrics
    if new_seed is None:
        console.print(
            "identical to original run" if same else "[yellow]differs from original run[/yellow]"
        )
    console.print(f"saved as [cyan]{rec.run_id}[/cyan]")


@app.command("delete")
def delete_cmd(
    run_id: str,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation.")] = False,
) -> None:
    """Delete a saved run (asks for confirmation)."""
    repo = _repo()
    rec = _resolve_runs(repo, [run_id])[0]
    if not yes and not typer.confirm(f"Delete {rec.label}?"):
        raise typer.Exit(1)
    repo.delete_run(rec.run_id)
    console.print(f"deleted {rec.run_id}")


# ---- real-network commands -------------------------------------------------------------
network_app = typer.Typer(
    help="Measure the network you are on, then simulate how it behaves under load."
)
app.add_typer(network_app, name="network")

PROFILE_KIND = "network"


def _load_profile(repo: Repository):
    from bufferlab.netprobe.profile import NetworkProfile

    d = repo.list_configs(PROFILE_KIND).get("latest")
    return NetworkProfile.from_dict(d) if d else None


def _profile_table(p) -> Table:
    t = Table(
        title="This network (measured)"
        if p.ping_target != "manual"
        else "This network (entered by hand)",
        show_header=False,
    )
    t.add_column(style="cyan")
    t.add_column()

    def pct(v):
        return "n/a" if v is None else f"{v * 100:.1f}%"

    t.add_row("Measured", p.taken_at)
    t.add_row("Download capacity", f"{p.capacity_mbps:.2f} Mbps")
    t.add_row("Idle latency (median RTT)", f"{p.idle_rtt_ms:.1f} ms")
    t.add_row(
        "Latency under load", "n/a" if p.loaded_rtt_ms is None else f"{p.loaded_rtt_ms:.1f} ms"
    )
    t.add_row("Packet loss idle / under load (ICMP)", f"{pct(p.idle_loss)} / {pct(p.loaded_loss)}")
    t.add_row("Estimated buffer", f"{p.buffer_pkts} packets  ({p.buffer_note})")
    return t


@network_app.command("probe")
def network_probe_cmd(
    target: Annotated[str, typer.Option(help="Host to ping (ICMP).")] = "1.1.1.1",
    seconds: Annotated[float, typer.Option(help="Download test length (4-30 s).")] = 8.0,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Consent without prompting.")] = False,
) -> None:
    """Measure capacity, latency and packet loss on this network (sends real traffic)."""
    from bufferlab.netprobe import probe as pr
    from bufferlab.netprobe.profile import NetworkProfile

    if not 4 <= seconds <= 30:
        _fail("--seconds must be between 4 and 30")
    host = pr.DEFAULT_URL.split("/")[2]
    if not yes and not typer.confirm(
        f"This pings {target} and downloads test data from {host} for ~{seconds:g}s, using your whole "
        f"connection (at most {pr.MAX_DOWNLOAD_BYTES // 1_000_000} MB). Continue?"
    ):
        raise typer.Exit(1)
    try:
        m = pr.run_probe(
            target, seconds=seconds, progress=lambda msg: err.print(f"[dim]{msg}[/dim]")
        )
    except pr.ProbeError as e:
        _fail(str(e), 1)
        return
    prof = NetworkProfile.from_measurement(m)
    _repo().save_config("latest", PROFILE_KIND, prof.to_dict())
    console.print(_profile_table(prof))
    console.print("Saved. Next: [cyan]bufferlab network predict[/cyan]")


@network_app.command("show")
def network_show_cmd() -> None:
    """Show the saved network profile."""
    p = _load_profile(_repo())
    if p is None:
        _fail(
            "no saved profile; run `bufferlab network probe` (or `predict --capacity-mbps ...`)", 1
        )
    console.print(_profile_table(p))


@network_app.command("predict")
def network_predict_cmd(
    loads: Annotated[
        str | None,
        typer.Option(
            help="Offered loads in Mbps, comma separated (default: 25%..200% of capacity)."
        ),
    ] = None,
    algorithms: Annotated[str, typer.Option(help="drop-tail,red,codel")] = "drop-tail",
    traffic: Annotated[str, typer.Option(help="poisson | constant | bursty")] = "poisson",
    capacity_mbps: Annotated[
        float | None, typer.Option(help="Use this capacity instead of the saved measurement.")
    ] = None,
    rtt_ms: Annotated[float, typer.Option(help="With --capacity-mbps: idle RTT.")] = 20.0,
    buffer_ms: Annotated[
        float, typer.Option(help="With --capacity-mbps: queueing delay when full.")
    ] = 20.0,
    seed: Annotated[int, typer.Option()] = 42,
) -> None:
    """Simulate this network at several offered loads: predicted throughput and packet loss."""
    from bufferlab.netprobe import whatif
    from bufferlab.netprobe.profile import NetworkProfile

    repo = _repo()
    if capacity_mbps is not None:
        prof = NetworkProfile.manual(capacity_mbps, rtt_ms, buffer_ms)
    else:
        prof = _load_profile(repo)
        if prof is None:
            _fail(
                "no measurement yet: run `bufferlab network probe` first, or pass --capacity-mbps",
                1,
            )
    algs = [a.strip() for a in algorithms.split(",") if a.strip()]
    bad = [a for a in algs if a not in algorithm_keys()]
    if bad:
        _fail(f"unknown algorithm(s): {', '.join(bad)}")
    try:
        load_list = (
            [float(x) for x in loads.split(",")]
            if loads
            else whatif.default_loads(prof.capacity_mbps)
        )
    except ValueError:
        _fail("--loads must be numbers in Mbps, e.g. 5,10,20")
    if any(x <= 0 for x in load_list):
        _fail("loads must be positive")
    console.print(_profile_table(prof))
    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=err,
        transient=True,
    ) as prog:
        task = prog.add_task("simulating", total=len(load_list) * len(algs))
        preds = whatif.predict(
            prof,
            load_list,
            algs,
            traffic,
            seed,
            on_run=repo.save_run,
            on_progress=lambda d, t: prog.update(task, completed=d),
        )
    t = Table(title="Predicted behaviour (SIMULATED from the measured values above)")
    heads = ("Load Mbps", "Load %", "Algorithm", "Thruput Mbps", "Loss", "Avg ms", "p95 ms")
    for col in heads:
        t.add_column(
            col, justify="left" if col == "Algorithm" else "right", no_wrap=True, overflow="fold"
        )

    for p in preds:
        loss = "n/a" if p.loss_rate is None else f"{p.loss_rate * 100:.2f}%"
        avg = "n/a" if p.avg_delay_ms is None else f"{p.avg_delay_ms:.1f}"
        p95 = "n/a" if p.p95_delay_ms is None else f"{p.p95_delay_ms:.1f}"
        t.add_row(
            f"{p.load_mbps:.1f}",
            f"{p.load_pct:.0f}%",
            p.algorithm,
            f"{p.throughput_mbps:.2f}",
            loss,
            avg,
            p95,
        )
    console.print(t)
    for a in algs:
        k = whatif.knee(preds, a)
        console.print(
            f"  {a}: "
            + (
                f"loss first exceeds 1% at about {k:g} Mbps offered"
                if k
                else "loss stayed under 1% at every tested load"
            )
        )
    console.print(
        "[dim]Model note: sources are open-loop (UDP-like / many independent users). Real TCP slows down "
        "when it sees loss, so real TCP loss would be lower and throughput closer to capacity. Runs are "
        "saved in History.[/dim]"
    )


def main() -> None:
    app(prog_name="bufferlab")


if __name__ == "__main__":
    main()
    sys.exit(0)
