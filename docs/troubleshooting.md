# Troubleshooting

**`bufferlab: command not found`** – activate the virtual environment, or use `python -m bufferlab`.

**Garbled characters / missing blocks in charts** – Settings (Ctrl+T) → *ASCII-only charts*. BufferLab enables this automatically when the
terminal reports a non-UTF-8 encoding. On Windows use Windows Terminal rather than the legacy console host.

**F-keys do nothing** – some terminals (macOS Terminal with media keys, GNOME Terminal F10/F1, tmux) intercept function keys. Use Ctrl+P (command palette)
or hold Fn. All screens are reachable from the palette.

**Colours look wrong on a light background** – Settings → Theme → Light.

**A run stops early with “event limit”** – raise `--max-events` or shorten the run; metrics cover only the simulated portion.

**`database is locked`** – another BufferLab process is writing; close it. Data lives in `bufferlab.sqlite3` in the data folder shown in Settings.

**Reset everything** – delete the data folder (or set `BUFFERLAB_HOME` to a fresh directory).

**Logs** – `logs/bufferlab.log` in the data folder; set `BUFFERLAB_LOG=DEBUG` for detail. Nothing is logged to the terminal.
