# Architecture

```
bufferlab/
  core/         scheduler, events, packets, links, traffic, metrics, simulator   (no UI, no storage)
  algorithms/   base interface, drop_tail, red, codel, registry (param specs, validation)
  netprobe/     probe (ping + HTTPS download), profile (measurement -> simulator parameters), whatif (predictions)
  experiments/  models (config + validation + RunRecord), scenarios, runner, batch (run a list of configs)
  storage/      SQLite: database, migrations (PRAGMA user_version), repositories
  analysis/     comparison (loss/throughput tables, observations), reporting (CSV/JSON/MD/text exports)
  tui/          Textual app, screens/, widgets/, styles/, keymap  (no algorithm or simulation logic)
  cli.py        Typer commands; `bufferlab` with no sub-command opens the TUI
  utils/        paths (per-user data dir), logging (key=value file log), validation types
```

Dependency direction: `core` ← `algorithms` ← `experiments` ← `storage`/`analysis` ← `cli`/`tui`. (`core.metrics` imports only the
`DropReason` enum from `algorithms.base`.) The simulator runs without the TUI, algorithms are testable without the simulator.

## Concurrency

The simulator is synchronous. The TUI runs it in a Textual thread worker; progress callbacks (≈10 Hz, wall clock) and completion are
marshalled with `call_from_thread`. Cancellation is a `threading.Event` checked every 1024 events. SQLite uses one connection guarded by a lock.

## Persistence

`runs` (config JSON, resolved algorithm params, metrics JSON, seed, versions, batch id), `run_series` (zlib-compressed JSON, ≤ 200 bins × 7 channels per run),
`saved_configs` (experiment configs and the measured network profile, kind `network`). Packet traces are never stored. Location:
`$BUFFERLAB_HOME` or the platform data directory (see README).

## TUI

`BufferLabApp` owns the repository, settings, selection state and the single `RunState` (status, progress, event log). Screens are installed once
and reused (state survives navigation); global keys are declared in `tui/keymap.py` and tested for uniqueness.
