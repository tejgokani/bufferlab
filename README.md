# BufferLab

A terminal-native laboratory for simulating, analysing and comparing network **queue-management algorithms**
(Drop-Tail, RED, CoDel) at a single bottleneck link.

> **BufferLab is a simulator and research tool, not a substitute for a validated production-network simulator**
> (ns-3, OMNeT++…) and not a measurement of any real network. Every number it shows comes from a simulation
> you ran; scenarios are *configurations*, never stored results.

## 1. What it does

It runs a deterministic discrete-event simulation of `sources → queue manager → bottleneck link → destination`,
measures throughput, loss, queueing delay and queue occupancy from the simulated events, stores every run in
SQLite, and lets you compare runs, run replicated experiment matrices, and export reports. A Textual TUI is the
primary interface; every feature is also available from the CLI.

## 2. The problem it investigates

*How do different queue-management mechanisms affect throughput, packet loss, queueing delay and latency under
varying traffic loads and bottleneck bandwidths?*

## 3. Key features

* Pure-Python event-driven simulator (priority-queue scheduler, seeded, faster than real time, no external tools).
* Drop-Tail, RED (EWMA, count-based drops, idle decay, optional gentle) and CoDel (RFC 8289 state machine).
* Constant, Poisson and on/off bursty traffic; multi-source; propagation delay; warm-up; event limit; cancellation.
* 15+ metrics with documented accounting (packet cohort + time window; `generated = delivered + dropped + unresolved`).
* TUI: dashboard with live cards/charts, validated experiment form, scenario library, algorithm lab, run comparison,
  history, results explorer, export centre, Research Mode, settings, contextual help — all keyboard driven.
* Reproducibility: same config + seed ⇒ identical results; software and schema versions stored with each run.
* Batch sweeps and research matrices with replications, mean / SD / 95 % t-interval, generated written reports.
* CSV / JSON / Markdown / plain-text export.

## 4. Architecture

`core/` (simulator) ← `algorithms/` ← `experiments/` ← `storage/` + `analysis/` ← `cli.py` + `tui/`.
The TUI contains no networking logic; the simulator and algorithms run without it. See [docs/architecture.md](docs/architecture.md).

## 5. Supported platforms

Python ≥ 3.11 on macOS, Linux and Windows 10/11. Nothing in the core uses shell commands or OS-specific APIs
(`pathlib`, `sqlite3`, `threading` only). **Tested so far: macOS (Apple Silicon) with Python 3.12 only.** Linux and Windows
are expected to work but have **not** been run — see [Known limitations](#15-known-limitations).

## 6. Prerequisites

Python 3.11+ and `pip`. Dependencies installed automatically: `textual`, `rich`, `typer`. No admin rights, Docker, ns-3 or
Mininet required, and no internet access is needed after installation.

## 7. Installation

### One-line install (no manual environment setup)

macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/tejgokani/bufferlab/main/install.sh | sh
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/tejgokani/bufferlab/main/install.ps1 | iex
```

This clones the repo to `~/bufferlab` (`%USERPROFILE%\bufferlab`), puts a `bufferlab` command on your PATH
(`~/.local/bin` on macOS/Linux; a user-PATH shim folder on Windows) and starts the first run. The launcher
(`bin/bufferlab`, `bin/bufferlab.cmd`) then does this **every time `bufferlab` runs**: find Python ≥ 3.11
(set `BUFFERLAB_PYTHON` to force one), create or repair `.venv` *inside the clone* if it is missing, broken or
older than `pyproject.toml`, install the package, and start BufferLab. If no suitable Python exists it prints the
install command for your OS and exits. Already cloned? Just run `./bin/bufferlab` (Windows: `bin\bufferlab.cmd`).

### Manual install

```bash
git clone <this repository> bufferlab && cd bufferlab
python -m venv .venv
```

Activate the environment:

| Shell | Command |
|---|---|
| macOS / Linux (bash, zsh) | `source .venv/bin/activate` |
| Windows PowerShell | `.venv\Scripts\Activate.ps1` |
| Windows Command Prompt | `.venv\Scripts\activate.bat` |

```bash
pip install -e .          # add ".[dev]" for pytest + ruff
bufferlab --version
```

(PowerShell may need `Set-ExecutionPolicy -Scope Process RemoteSigned` once to allow the activation script.)
Prefer [uv](https://github.com/astral-sh/uv)? `uv venv && uv pip install -e ".[dev]"` works too.

## 8. Running the TUI

```bash
bufferlab            # or: python -m bufferlab
```

| Key | Screen |
|---|---|
| F1 | Help & About |
| F2 | Dashboard |
| F3 | New Experiment (Ctrl+R run, Ctrl+S save config) |
| F4 | Compare Runs (Space mark, S sort metric) |
| F5 | Experiment History (/ search, Space mark, Enter open, U duplicate, R rerun, D delete) |
| F6 | Export Center (Ctrl+E export) |
| F7 | Scenario Library (R run, C run with all 3 algorithms and compare) |
| F8 | Algorithm Lab (Ctrl+R trial, Ctrl+S save parameter set) |
| F9 | Results Explorer |
| F10 | Research Mode (Ctrl+R run matrix, Ctrl+W write report) |
| Ctrl+T | Settings |
| ? | Contextual help for the current screen |
| Esc | Cancel a running simulation (Dashboard) / go back |
| q | Quit on the Dashboard, otherwise back to the Dashboard |
| Ctrl+P | Command palette (also lists every screen, for terminals that swallow F-keys) |

The footer always shows the active bindings. Works from 80 columns up; an ASCII-only chart mode is in Settings.

## 9. Running experiments from the CLI

```bash
bufferlab scenarios                                   # list scenarios
bufferlab algorithms                                  # list algorithms and parameters
bufferlab run --scenario heavy-congestion --algorithm codel
bufferlab run -s small-buffer -a red -p max_p=0.3 -p weight=0.02 --seed 7 --duration 60 --warmup 10
bufferlab history [-q SEARCH] [-a ALGORITHM]
bufferlab show RUN_ID
bufferlab compare RUN_ID_1 RUN_ID_2 [...]
bufferlab export RUN_ID [RUN_ID ...] --format csv|json|md|txt [-o FILE]
bufferlab rerun RUN_ID [--new-seed N]                 # same seed => identical result
bufferlab delete RUN_ID                               # asks for confirmation (-y to skip)
bufferlab plot RUN_ID [RUN_ID ...] -o plot.png [--kind series|bars]   # needs: pip install "bufferlab[plots]"
bufferlab measure --host SERVER [--udp] [--duration 10]                # optional iperf3 measurement, asks first
bufferlab batch -s approaching-saturation --vary algorithm=drop-tail,red,codel \
        --vary offered_load_pct=50,100,150 --reps 5 --report report.md
bufferlab research --reps 5 --report research.md      # algorithm x load x buffer matrix
bufferlab export --batch BATCH_ID --format md         # re-render a stored batch report
```

Every command accepts `--help`. `RUN_ID` may be any unambiguous prefix.

## 10. Example configurations

Built-in scenarios (all 10 Mbps / 1500 B packets / Poisson unless noted; durations include warm-up in the table of `bufferlab scenarios`):

| Scenario | Key parameters |
|---|---|
| Light Traffic | load 30 % |
| Approaching Saturation | load 90 % |
| Heavy Congestion | load 130 % |
| Bursty Traffic | 4 on/off sources, avg load 80 %, 60 s |
| Small Buffer | load 95 %, 8-packet buffer |
| Large Buffer | load 110 %, 500-packet buffer |
| Low-Bandwidth Link | 1 Mbps, load 100 %, 60 s |
| High-Bandwidth Link | 1 Gbps, load 95 %, 200-packet buffer, 5 s |

Any field can be overridden (`--load`, `--capacity`, `--bandwidth`, `--packet-size`, `--traffic`, `--sources`, `--duration`,
`--warmup`, `--seed`, `--prop-delay`, `--param key=value`).

## 11. Understanding the metrics

Offered load vs delivered throughput, packet-loss rate (`dropped / generated`, warm-up excluded, unresolved packets reported
separately), queueing delay (mean / median / p95 / max — **not RTT**), queue occupancy, link and queue utilisation. Exact
definitions and denominators: [docs/metrics.md](docs/metrics.md). Model assumptions: [docs/simulation-model.md](docs/simulation-model.md).

## 12. Understanding the algorithms

Equations, parameters, defaults and deviations from the reference descriptions: [docs/algorithms.md](docs/algorithms.md).
RED and CoDel are simplified, unvalidated implementations (drop-only, no ECN) and make no claim of compliance with any
operating-system implementation.

## 13. Exporting results

TUI: F6. CLI: `bufferlab export …`. CSV has one row per run (config, resolved parameters, seed, versions and all metrics);
JSON adds time series; Markdown/text produce a report with configuration, metric definitions, results, automated observations and
limitations. Batch/research reports add objective, methodology, mean ± 95 % CI tables and questions for further investigation.
Default folder: `<data dir>/exports`. Method: [docs/research-methodology.md](docs/research-methodology.md).

Data directory: macOS `~/Library/Application Support/BufferLab`, Linux `$XDG_DATA_HOME/bufferlab` (default `~/.local/share/bufferlab`),
Windows `%APPDATA%\BufferLab`; override with `BUFFERLAB_HOME`.

## 14. Running tests

```bash
pip install -e ".[dev]"
pytest              # unit, simulation, integration (CLI) and TUI (Textual pilot) tests
ruff check .
```

The TUI tests drive the real app headlessly; they need no terminal. Each test uses an isolated `BUFFERLAB_HOME`.

## 15. Known limitations

* Open-loop sources and one bottleneck: no TCP congestion control, retransmissions, RTT or multi-hop behaviour; results do not
  predict real TCP throughput.
* RED/CoDel unvalidated against reference implementations; drop-only (no ECN); fixed packet size.
* Not implemented: stored packet traces, PIE/FQ-CoDel (the registry is designed for them).
* `bufferlab measure` (iperf3) is tested against parsed iperf3 JSON and a stand-in executable only; no live iperf3 server run was made.
* Local tests ran on macOS only. The GitHub Actions workflow runs the suite and the launcher on Ubuntu, macOS and Windows; see the badge/Actions tab for the actual status.
* The TUI was exercised through headless pilot tests, SVG screenshots and a pty launch on macOS; it has not been checked in
  other terminal emulators.
* Python-speed ceiling: roughly 300k events/s; the 1 Gbps scenario (~800k events) takes a few seconds.

## 16. Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md).

## 17. Contributing

1. `pip install -e ".[dev]"`; run `pytest` and `ruff check .` before opening a PR.
2. Keep simulation/algorithm logic out of `tui/`, and every displayed number traceable to a simulation or documented formula.
3. New algorithms: subclass `QueueManager`, register in `algorithms/registry.py` with `ParamSpec`s, document the equations and
   deviations in `docs/algorithms.md`, and add deterministic unit tests.
4. Changing metric definitions requires bumping `SCHEMA_VERSION` and updating `docs/metrics.md`.

Licensed under MIT.
