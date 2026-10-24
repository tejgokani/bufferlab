# BufferLab

A terminal-native laboratory for simulating, analysing and comparing network **queue-management algorithms**
(Drop-Tail, RED, CoDel) at a single bottleneck link.

> **BufferLab is a simulator, not a substitute for a validated production-network simulator**
> (ns-3, OMNeT++…) and not a measurement of any real network. Every number it shows comes from a simulation
> you ran; scenarios are *configurations*, never stored results.

## What it does

**BufferLab measures the real network you are on, then simulates how that network behaves under other loads and tells you the
packet loss and throughput it would deliver.**

1. `bufferlab network probe` (or F8 → `p`): pings and downloads for ~15 s (asks first) → capacity, idle/loaded latency, packet loss, estimated buffer.
2. `bufferlab network predict` (or F8 → `r`): a discrete-event simulation configured from those measurements, at 25 %…200 % of capacity
   (or your own Mbps list) → predicted **throughput and packet loss** (plus queueing delay) per load, for Drop-Tail, RED or CoDel queues.

Measured numbers and simulated numbers are labelled separately everywhere. Details and caveats: [docs/my-network.md](docs/my-network.md).
Beyond your own network it is a general loss/throughput simulator: scenarios, a validated configuration form, run comparison, history and export.

> BufferLab is a simulator, not a substitute for a validated production-network simulator such as ns-3. Predictions assume
> open-loop (non-TCP-adaptive) traffic; see the limitations.

## Key features

* Real-network probe (ping + HTTPS download, no admin rights) → simulator parameters.
* Deterministic discrete-event simulator, Drop-Tail / RED / CoDel, constant / Poisson / bursty traffic, seeded and reproducible.
* Loss- and throughput-first metrics with documented accounting (`generated = delivered + dropped + unresolved`), see [docs/metrics.md](docs/metrics.md).
* Textual TUI (Dashboard, My Network, New Experiment, Scenarios, Compare, History, Results, Export) and a CLI for everything.
* SQLite history; CSV / JSON / Markdown / text export.

## Installation

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

## Running the TUI

```bash
bufferlab            # or: python -m bufferlab
```

| Key | Screen |
|---|---|
| F1 | Help & About |
| F2 | Dashboard |
| F3 | New Experiment (Ctrl+R run, Ctrl+S save config) |
| F4 | Compare Runs (Space mark, S sort metric; loss/throughput first) |
| F5 | Experiment History (/ search, Space mark, Enter open, U duplicate, R rerun, D delete) |
| F6 | Export Center (Ctrl+E export) |
| F7 | Scenario Library (R run, C run with all 3 algorithms and compare) |
| F8 | **My Network**: `p` measure your network, `r` predict loss & throughput, `x` cancel |
| F9 | Results Explorer |
| Ctrl+T | Settings |
| ? | Contextual help for the current screen |
| Esc | Cancel a running simulation (Dashboard) / go back |
| q | Quit on the Dashboard, otherwise back to the Dashboard |
| Ctrl+P | Command palette (also lists every screen, for terminals that swallow F-keys) |

The footer always shows the active bindings. Works from 80 columns up; an ASCII-only chart mode is in Settings.

## CLI

```bash
bufferlab network probe                               # measure this network (asks first)
bufferlab network predict [--loads 5,10,20] [--algorithms drop-tail,red,codel] [--traffic bursty]
bufferlab network show                                # saved measurement
bufferlab network predict --capacity-mbps 50 --rtt-ms 30 --buffer-ms 100   # no measurement: type it in
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
```

Every command accepts `--help`. `RUN_ID` may be any unambiguous prefix.

## Built-in scenarios

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

## Understanding the metrics

Offered load vs delivered throughput, packet-loss rate (`dropped / generated`, warm-up excluded, unresolved packets reported
separately), queueing delay (mean / median / p95 / max — **not RTT**), queue occupancy, link and queue utilisation. Exact
definitions and denominators: [docs/metrics.md](docs/metrics.md). Model assumptions: [docs/simulation-model.md](docs/simulation-model.md).

## Understanding the algorithms

Equations, parameters, defaults and deviations from the reference descriptions: [docs/algorithms.md](docs/algorithms.md).
RED and CoDel are simplified, unvalidated implementations (drop-only, no ECN) and make no claim of compliance with any
operating-system implementation.

## Exporting results

TUI: F6. CLI: `bufferlab export …`. CSV has one row per run (config, resolved parameters, seed, versions and all metrics);
JSON adds time series; Markdown/text produce a report with configuration, metric definitions, results, automated observations and
limitations. Default folder: `<data dir>/exports`. 

Data directory: macOS `~/Library/Application Support/BufferLab`, Linux `$XDG_DATA_HOME/bufferlab` (default `~/.local/share/bufferlab`),
Windows `%APPDATA%\BufferLab`; override with `BUFFERLAB_HOME`.

## Running tests

```bash
pip install -e ".[dev]"
pytest              # unit, simulation, integration (CLI) and TUI (Textual pilot) tests
ruff check .
```

The TUI tests drive the real app headlessly; they need no terminal. Each test uses an isolated `BUFFERLAB_HOME`.

## Known limitations

* **Predictions assume open-loop traffic** (sources do not slow down on loss, like UDP/video/many users). Real TCP backs off, so its loss is lower and its
  throughput closer to capacity. One bottleneck, no RTT/multi-hop modelling. Capacity is measured to a single server in the download direction;
  buffer size is inferred from latency growth; ICMP loss differs from what applications see ([docs/my-network.md](docs/my-network.md)).
* RED/CoDel unvalidated against reference implementations; drop-only (no ECN); fixed packet size.
* Not implemented: upload-direction measurement, stored packet traces, PIE/FQ-CoDel.
* Everything was tested on macOS only (no CI is shipped). Linux/Windows are expected to work (stdlib + system `ping` with per-OS flags) but are unverified; the Windows launcher/installer have never been run.
* The TUI was exercised through headless pilot tests, SVG screenshots and a pty launch on macOS; it has not been checked in
  other terminal emulators.
* Python-speed ceiling: roughly 300k events/s; the 1 Gbps scenario (~800k events) takes a few seconds.

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md).

## Contributing

1. `pip install -e ".[dev]"`; run `pytest` and `ruff check .` before opening a PR.
2. Keep simulation/algorithm logic out of `tui/`, and every displayed number traceable to a simulation or documented formula.
3. New algorithms: subclass `QueueManager`, register in `algorithms/registry.py` with `ParamSpec`s, document the equations and
   deviations in `docs/algorithms.md`, and add deterministic unit tests.
4. Changing metric definitions requires bumping `SCHEMA_VERSION` and updating `docs/metrics.md`.

Licensed under MIT.
