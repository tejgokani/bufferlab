"""My Network: measure the real network, then simulate how it behaves under load."""

from __future__ import annotations

import threading

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Label, Select, Static

from bufferlab.netprobe import probe as pr
from bufferlab.netprobe import whatif
from bufferlab.netprobe.profile import NetworkProfile
from bufferlab.netprobe.whatif import Prediction
from bufferlab.tui.screens.base import LabScreen
from bufferlab.tui.screens.modals import ConfirmModal

PROFILE_KIND = "network"
ALG_CHOICES = [
    ("Drop-Tail only (typical router today)", "drop-tail"),
    ("Compare Drop-Tail, RED and CoDel", "all"),
]
TRAFFIC_CHOICES = [
    ("Poisson (many independent users)", "poisson"),
    ("Bursty (video / web bursts)", "bursty"),
    ("Constant rate (streaming/VoIP)", "constant"),
]


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


class NetworkScreen(LabScreen):
    NAME = "network"
    TITLE_TEXT = "My Network"
    BINDINGS = [
        Binding("p", "probe", "Measure network"),
        Binding("r", "predict", "Predict"),
        Binding("x", "cancel", "Cancel"),
    ]
    HELP = (
        "My Network\n\nPress p to MEASURE the network this computer is on: idle latency and packet loss "
        "(ping), then maximum download throughput while pinging again (latency and loss under load, "
        "which reveals how much buffering the path has). This sends real traffic, so you are asked first.\n\n"
        "Press r to SIMULATE that network at different offered loads. The simulator is configured from "
        "the measured capacity, latency and buffer size, and reports the throughput and packet loss it "
        "predicts for each load. Left side = measured; right/below = simulated.\n\n"
        "Important: sources in the simulation are open-loop (they do not slow down when packets are lost, "
        "like UDP, video calls or many independent users). Real TCP backs off, so its loss would be lower. "
        "Capacity is measured to one speed-test server; the buffer size is inferred from latency growth."
    )

    def __init__(self) -> None:
        super().__init__()
        self.profile: NetworkProfile | None = None
        self.preds: list[Prediction] = []
        self._cancel = threading.Event()
        self._busy = False

    def body(self) -> ComposeResult:
        with Horizontal(id="net-top"):
            with Vertical(classes="panel", id="net-measured"):
                yield Static("Measured on this network (real traffic)", classes="title")
                yield Static(id="profile")
                yield Static(id="probe-status")
                yield Button("Measure my network (p)", id="btn-probe", variant="primary")
            with Vertical(classes="panel", id="net-whatif"):
                yield Static("What if… (simulated from the measurements)", classes="title")
                yield Horizontal(
                    Label("Offered loads (Mbps)"),
                    Input(placeholder="blank = 25%…200% of capacity", id="loads"),
                    classes="form-row",
                )
                yield Horizontal(
                    Label("Queue algorithm"),
                    Select(ALG_CHOICES, value="drop-tail", allow_blank=False, id="algs"),
                    classes="form-row",
                )
                yield Horizontal(
                    Label("Traffic type"),
                    Select(TRAFFIC_CHOICES, value="poisson", allow_blank=False, id="traffic"),
                    classes="form-row",
                )
                yield Button("Predict loss & throughput (r)", id="btn-predict", variant="success")
                yield Static(id="predict-status")
        with Vertical(classes="panel", id="net-results"):
            yield DataTable(id="tbl", cursor_type="row", zebra_stripes=True)
            yield Static(id="summary")

    def on_mount(self) -> None:
        super().on_mount()
        t = self.query_one("#tbl", DataTable)
        t.add_columns(
            "Offered",
            "% of capacity",
            "Algorithm",
            "Throughput",
            "Packet loss",
            "Avg queue delay",
            "p95 queue delay",
        )
        self.load_saved()

    def on_screen_resume(self) -> None:
        self.load_saved()

    # -- profile ----------------------------------------------------------------------
    def load_saved(self) -> None:
        d = self.app.repo.list_configs(PROFILE_KIND).get("latest")
        if d:
            self.profile = NetworkProfile.from_dict(d)
        self.render_profile()

    def render_profile(self) -> None:
        w = self.query_one("#profile", Static)
        p = self.profile
        if p is None:
            w.update(
                Text(
                    "Nothing measured yet.\n\nPress p to measure this network (about 15 seconds). "
                    "It pings 1.1.1.1 and downloads test data from speed.cloudflare.com, and asks you first.",
                    style="dim",
                )
            )
            return
        t = Text()
        rows = [
            ("Measured", p.taken_at.replace("T", " ")),
            ("Download capacity", f"{p.capacity_mbps:.1f} Mbps"),
            (
                "Latency idle / loaded",
                f"{p.idle_rtt_ms:.0f} ms / "
                + ("n/a" if p.loaded_rtt_ms is None else f"{p.loaded_rtt_ms:.0f} ms"),
            ),
            ("Packet loss idle / loaded", f"{_pct(p.idle_loss)} / {_pct(p.loaded_loss)}  (ICMP)"),
            ("Buffer (estimated)", f"{p.buffer_pkts} packets"),
        ]
        for k, v in rows:
            t.append(f"{k:<26}", style="cyan")
            t.append(f"{v}\n")
        t.append(p.buffer_note, style="dim")
        w.update(t)

    def action_probe(self) -> None:
        if self._busy:
            return
        host = pr.DEFAULT_URL.split("/")[2]
        msg = (
            f"Measure this network?\n\nThis sends real traffic: it pings {pr.DEFAULT_TARGET} and downloads "
            f"test data from {host} for about 8 seconds, using your whole connection "
            f"(at most {pr.MAX_DOWNLOAD_BYTES // 1_000_000} MB). Nothing else is changed or uploaded."
        )

        def done(yes: bool | None) -> None:
            if yes:
                self._start_probe()

        self.app.push_screen(ConfirmModal(msg, "Measure"), done)

    def _start_probe(self) -> None:
        self._busy = True
        self._cancel = threading.Event()
        self.query_one("#probe-status", Static).update(Text("starting…", style="cyan"))

        def work() -> None:
            try:
                m = pr.run_probe(
                    progress=lambda s: self.app.call_from_thread(self._probe_msg, s),
                    cancel=self._cancel,
                )
                prof = NetworkProfile.from_measurement(m)
                self.app.repo.save_config("latest", PROFILE_KIND, prof.to_dict())
                self.app.call_from_thread(self._probe_done, prof, None)
            except pr.ProbeError as exc:
                self.app.call_from_thread(self._probe_done, None, str(exc))

        self.app.run_worker(work, thread=True, group="probe", exclusive=True, name="probe")

    def _probe_msg(self, s: str) -> None:
        self.query_one("#probe-status", Static).update(Text(s, style="cyan"))

    def _probe_done(self, prof: NetworkProfile | None, error: str | None) -> None:
        self._busy = False
        st = self.query_one("#probe-status", Static)
        if error:
            st.update(Text(f"✗ {error}", style="red"))
            return
        self.profile = prof
        st.update(Text("✓ measured and saved", style="green"))
        self.render_profile()

    # -- prediction ---------------------------------------------------------------------
    def action_predict(self) -> None:
        if self._busy:
            return
        if self.profile is None:
            self.app.notify("Measure your network first (p).", severity="warning")
            return
        text = self.query_one("#loads", Input).value.strip()
        try:
            loads = (
                [float(x) for x in text.split(",") if x.strip()]
                if text
                else whatif.default_loads(self.profile.capacity_mbps)
            )
        except ValueError:
            self.query_one("#predict-status", Static).update(
                Text("✗ loads must be numbers in Mbps, e.g. 5,10,20", style="red")
            )
            return
        if not loads or any(x <= 0 for x in loads):
            self.query_one("#predict-status", Static).update(
                Text("✗ loads must be positive", style="red")
            )
            return
        algs_sel = self.query_one("#algs", Select).value
        algs = list(whatif.ALGORITHMS) if algs_sel == "all" else ["drop-tail"]
        traffic = self.query_one("#traffic", Select).value
        self._busy = True
        self._cancel = threading.Event()
        self.preds = []
        self.query_one("#tbl", DataTable).clear()
        prof = self.profile

        def work() -> None:
            try:

                def on_run(rec) -> None:
                    self.app.repo.save_run(rec)

                preds = whatif.predict(
                    prof,
                    loads,
                    algs,
                    traffic,
                    on_run=on_run,
                    cancel=self._cancel,
                    on_progress=lambda d, t: self.app.call_from_thread(self._pred_progress, d, t),
                )
                self.app.call_from_thread(self._pred_done, preds, None)
            except Exception as exc:
                self.app.call_from_thread(self._pred_done, [], f"{type(exc).__name__}: {exc}")

        self.app.run_worker(work, thread=True, group="predict", exclusive=True, name="predict")

    def _pred_progress(self, done: int, total: int) -> None:
        self.query_one("#predict-status", Static).update(
            Text(f"simulating {done}/{total}…", style="cyan")
        )

    def _pred_done(self, preds: list[Prediction], error: str | None) -> None:
        self._busy = False
        st = self.query_one("#predict-status", Static)
        if error:
            st.update(Text(f"✗ {error}", style="red"))
            return
        self.preds = preds
        t = self.query_one("#tbl", DataTable)
        t.clear()
        for p in preds:
            loss_style = (
                "green" if (p.loss_rate or 0) < 0.01 else "yellow" if p.loss_rate < 0.05 else "red"
            )
            t.add_row(
                f"{p.load_mbps:.1f} Mbps",
                f"{p.load_pct:.0f}%",
                p.algorithm,
                f"{p.throughput_mbps:.2f} Mbps",
                Text(
                    "n/a" if p.loss_rate is None else f"{p.loss_rate * 100:.2f}%", style=loss_style
                ),
                "n/a" if p.avg_delay_ms is None else f"{p.avg_delay_ms:.1f} ms",
                "n/a" if p.p95_delay_ms is None else f"{p.p95_delay_ms:.1f} ms",
            )
        st.update(
            Text(
                f"✓ {len(preds)} simulations saved to History" if preds else "cancelled",
                style="green" if preds else "yellow",
            )
        )
        self.render_summary()

    def render_summary(self) -> None:
        s = Text("SIMULATED prediction, not a measurement. ", style="bold")
        for a in dict.fromkeys(p.algorithm for p in self.preds):
            k = whatif.knee(self.preds, a)
            s.append(
                f"{a}: "
                + (
                    f"loss exceeds 1% from about {k:g} Mbps offered. "
                    if k
                    else "loss stays under 1% at every tested load. "
                )
            )
        s.append(
            "\nOpen-loop sources: real TCP would back off and lose less (F1/? for details).",
            style="dim",
        )
        self.query_one("#summary", Static).update(s)

    def action_cancel(self) -> None:
        self._cancel.set()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-probe":
            self.action_probe()
        elif event.button.id == "btn-predict":
            self.action_predict()
