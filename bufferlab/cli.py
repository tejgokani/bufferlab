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
from bufferlab.analysis.reporting import FORMATS, export_batch, export_runs
from bufferlab.core.traffic import TRAFFIC_MODELS
from bufferlab.experiments.batch import BatchSpec, research_matrix, run_batch
from bufferlab.experiments.models import ConfigError, ExperimentConfig, RunRecord
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


def _parse_vary(items: list[str]) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for it in items:
        if "=" not in it:
            _fail(f"--vary expects key=v1,v2,..., got {it!r}")
        k, v = it.split("=", 1)
        out[k.strip()] = [_parse_scalar(x) for x in v.split(",") if x.strip()]
    return out


def _execute_batch(spec: BatchSpec, save: bool, report: Path | None, fmt: str) -> None:
    for e in spec.validate():
        _fail(e)
    total = spec.total_runs()
    console.print(
        f"[bold]{spec.name}[/bold]: {len(spec.points())} points x {spec.replications} replication(s) = {total} runs"
    )
    repo = _repo() if save else None
    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=err,
        transient=True,
    ) as prog:
        task = prog.add_task("running", total=total)

        def on_prog(done: int, tot: int, label: str) -> None:
            prog.update(task, completed=done, description=label[:60])

        try:
            result = run_batch(spec, on_prog, on_run=(repo.save_run if repo else None))
        except (ConfigError, ValueError) as e:
            _fail(str(e))
            return
    if repo:
        repo.save_batch(result.batch_id, spec)
    from bufferlab.analysis.reporting import batch_report

    doc = batch_report(spec, result.runs)
    from rich.markdown import Markdown

    console.print(Markdown(doc.to_markdown()))
    if save:
        console.print(f"batch id [cyan]{result.batch_id}[/cyan]  ({len(result.runs)} runs saved)")
    if report:
        p = export_batch(spec, result.runs, fmt, report)
        console.print(f"report written to {p}")


@app.command("batch")
def batch_cmd(
    scenario: Annotated[str, typer.Option("--scenario", "-s")] = "approaching-saturation",
    algorithm: Annotated[
        str, typer.Option("--algorithm", "-a", help="Base algorithm (or vary it).")
    ] = "drop-tail",
    vary: Annotated[
        list[str] | None,
        typer.Option(
            "--vary",
            "-v",
            help="Factor sweep, e.g. offered_load_pct=50,100,150 or param.max_p=0.05,0.2 or algorithm=drop-tail,red (repeatable).",
        ),
    ] = None,
    reps: Annotated[int, typer.Option(help="Replications per point (seeds base+0..n-1).")] = 5,
    seed: Annotated[int | None, typer.Option(help="Base seed.")] = None,
    duration: Annotated[float | None, typer.Option()] = None,
    warmup: Annotated[float | None, typer.Option()] = None,
    name: Annotated[str, typer.Option()] = "batch",
    no_save: Annotated[bool, typer.Option("--no-save")] = False,
    report: Annotated[Path | None, typer.Option(help="Write a report to this path.")] = None,
    fmt: Annotated[str, typer.Option("--format", help="Report format: md, txt, json, csv")] = "md",
) -> None:
    """Run a parameter sweep with repeated runs and print mean +/- 95% CI."""
    base = _build_config(
        scenario,
        algorithm,
        name,
        None,
        None,
        None,
        None,
        None,
        None,
        duration,
        warmup,
        seed,
        None,
        None,
        None,
    )
    spec = BatchSpec(name, base, _parse_vary(vary or []), reps, seed)
    _execute_batch(spec, not no_save, report, fmt)


@app.command("research")
def research_cmd(
    scenario: Annotated[str, typer.Option("--scenario", "-s")] = "approaching-saturation",
    loads: Annotated[str, typer.Option(help="Offered loads, % of capacity.")] = "50,75,100,125,150",
    capacities: Annotated[
        str, typer.Option(help="Queue capacities (packets): small,medium,large.")
    ] = "10,50,250",
    algorithms: Annotated[
        str, typer.Option(help="Comma-separated algorithms.")
    ] = "drop-tail,red,codel",
    reps: Annotated[int, typer.Option()] = 5,
    seed: Annotated[int | None, typer.Option()] = None,
    duration: Annotated[float | None, typer.Option()] = None,
    warmup: Annotated[float | None, typer.Option()] = None,
    objective: Annotated[
        str, typer.Option(help="Objective text for the report.")
    ] = "How do offered load and buffer size affect queueing delay and loss under each queue-management algorithm?",
    name: Annotated[str, typer.Option()] = "research-matrix",
    no_save: Annotated[bool, typer.Option("--no-save")] = False,
    report: Annotated[Path | None, typer.Option(help="Write a report to this path.")] = None,
    fmt: Annotated[str, typer.Option("--format")] = "md",
) -> None:
    """Run the algorithm x load x buffer experiment matrix (Research Mode)."""
    base = _build_config(
        scenario,
        "drop-tail",
        name,
        None,
        None,
        None,
        None,
        None,
        None,
        duration,
        warmup,
        seed,
        None,
        None,
        None,
    )
    try:
        spec = research_matrix(
            base,
            algorithms=[a.strip() for a in algorithms.split(",")],
            load_pcts=[float(x) for x in loads.split(",")],
            capacities=[int(x) for x in capacities.split(",")],
            replications=reps,
            name=name,
            objective=objective,
        )
    except ValueError as e:
        _fail(str(e))
        return
    _execute_batch(spec, not no_save, report, fmt)


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
    batch: Annotated[
        str | None, typer.Option("--batch", help="Export a whole batch report instead.")
    ] = None,
    fmt: Annotated[str, typer.Option("--format", "-f", help=f"{', '.join(FORMATS)}")] = "csv",
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
) -> None:
    """Export runs (or a batch report) to CSV, JSON, Markdown or text."""
    if fmt not in FORMATS:
        _fail(f"unsupported format {fmt!r}; choose from {', '.join(FORMATS)}")
    repo = _repo()
    if batch:
        try:
            spec, runs = repo.get_batch(batch)
        except NotFoundError as e:
            _fail(str(e), 1)
            return
        out = output or exports_dir() / f"batch-{batch}.{fmt}"
        console.print(f"wrote {export_batch(spec, runs, fmt, out)}")
        return
    if not run_ids:
        _fail("give RUN_ID(s) or --batch BATCH_ID")
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


@app.command("plot")
def plot_cmd(
    run_ids: Annotated[list[str], typer.Argument(help="Run IDs to plot.")],
    output: Annotated[Path, typer.Option("--output", "-o", help="PNG/SVG/PDF file.")],
    kind: Annotated[
        str, typer.Option(help="series (time series) or bars (metric comparison)")
    ] = "series",
) -> None:
    """Export Matplotlib plots (needs: pip install "bufferlab[plots]")."""
    from bufferlab.analysis.plots import plot_comparison, plot_runs

    runs = _resolve_runs(_repo(), run_ids)
    try:
        out = (plot_runs if kind == "series" else plot_comparison)(runs, output)
    except RuntimeError as e:
        _fail(str(e))
        return
    console.print(f"wrote {out}")


@app.command("measure")
def measure_cmd(
    host: Annotated[
        str | None, typer.Option(help="iperf3 server to test against (required to run).")
    ] = None,
    port: Annotated[int, typer.Option()] = 5201,
    duration: Annotated[int, typer.Option(help="Seconds (1-600).")] = 10,
    udp: Annotated[bool, typer.Option("--udp", help="Use UDP instead of TCP.")] = False,
    udp_rate: Annotated[float | None, typer.Option(help="UDP target rate, Mbps.")] = None,
    reverse: Annotated[
        bool, typer.Option("--reverse", help="Server sends to this machine.")
    ] = False,
    parallel: Annotated[int, typer.Option(help="Parallel streams (1-16).")] = 1,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Confirm sending traffic without prompting.")
    ] = False,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Write the measurement as JSON.")
    ] = None,
) -> None:
    """Optional real-network measurement with iperf3 (separate from simulations)."""
    from bufferlab.measure import iperf

    exe = iperf.find_iperf3()
    if exe is None:
        err.print(f"[yellow]{iperf.INSTALL_HINT}[/yellow]")
    else:
        console.print(f"iperf3 found: {exe}")
    if host is None:
        console.print(
            "Give --host SERVER to run a measurement. Nothing is sent without an explicit host and confirmation."
        )
        raise typer.Exit(0 if exe else 1)
    if not yes and not typer.confirm(
        f"Send {'UDP' if udp else 'TCP'} test traffic to {host}:{port} for {duration}s?"
    ):
        raise typer.Exit(1)
    try:
        res = iperf.run_client(
            host,
            port,
            duration,
            "udp" if udp else "tcp",
            reverse,
            udp_rate,
            parallel,
            confirmed=True,
        )
    except iperf.MeasureError as e:
        _fail(str(e), 1)
        return
    t = Table(title="Measured (iperf3) - not a simulation result", show_header=False)
    for k, v in res.to_dict().items():
        t.add_row(k, str(v))
    console.print(t)
    if output:
        import json as _json

        output.write_text(_json.dumps(res.to_dict(), indent=2), encoding="utf-8")
        console.print(f"wrote {output}")


def main() -> None:
    app(prog_name="bufferlab")


if __name__ == "__main__":
    main()
    sys.exit(0)
