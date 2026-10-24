import json

from typer.testing import CliRunner

from bufferlab import __version__
from bufferlab.cli import app

runner = CliRunner()
FAST = ["--duration", "6", "--warmup", "1"]


def ids(output):
    import re

    return re.findall(r"\br[0-9a-f]{9}\b", output)


def test_version_and_help():
    r = runner.invoke(app, ["--version"])
    assert r.exit_code == 0 and __version__ in r.output
    for cmd in (
        "run",
        "history",
        "compare",
        "export",
        "scenarios",
        "algorithms",
    ):
        assert runner.invoke(app, [cmd, "--help"]).exit_code == 0


def test_scenarios_and_algorithms():
    out = runner.invoke(app, ["scenarios"]).output
    assert "heavy-congestion" in out and "bursty-traffic" in out
    assert "codel" in runner.invoke(app, ["algorithms"]).output


def test_full_user_flow(tmp_path):
    a = runner.invoke(app, ["run", "-s", "heavy-congestion", "-a", "drop-tail", *FAST])
    b = runner.invoke(app, ["run", "-s", "heavy-congestion", "-a", "codel", *FAST])
    assert a.exit_code == 0 and b.exit_code == 0, a.output + b.output
    ida, idb = ids(a.output)[-1], ids(b.output)[-1]
    h = runner.invoke(app, ["history"]).output
    assert ida in h and idb in h
    assert ida in runner.invoke(app, ["history", "-q", "drop-tail"]).output
    c = runner.invoke(app, ["compare", ida, idb])
    assert c.exit_code == 0 and "Observations" in c.output
    out = tmp_path / "e.csv"
    e = runner.invoke(app, ["export", ida, idb, "-f", "csv", "-o", str(out)])
    assert e.exit_code == 0 and out.exists() and ida in out.read_text()
    j = tmp_path / "e.json"
    runner.invoke(app, ["export", ida, "-f", "json", "-o", str(j)])
    assert json.loads(j.read_text())["runs"][0]["run_id"] == ida
    s = runner.invoke(app, ["show", ida])
    assert s.exit_code == 0 and "Delivered throughput" in s.output
    r = runner.invoke(app, ["rerun", ida])
    assert "identical to original run" in r.output  # reproducibility
    d = runner.invoke(app, ["delete", ida, "--yes"])
    assert d.exit_code == 0 and ida not in runner.invoke(app, ["history"]).output


def test_errors_are_clear():
    assert runner.invoke(app, ["run", "-a", "nope"]).exit_code == 2
    r = runner.invoke(app, ["run", "--duration", "3", "--warmup", "3"])
    assert r.exit_code == 2
    assert runner.invoke(app, ["compare", "rxxxxxxxxx", "ryyyyyyyyy"]).exit_code == 1
    assert runner.invoke(app, ["compare", "onlyone"]).exit_code == 2
    assert runner.invoke(app, ["export", "-f", "csv"]).exit_code == 2


def test_red_param_flag_and_delete_confirm():
    r = runner.invoke(app, ["run", "-a", "red", "-p", "max_p=0.4", "--no-save", *FAST])
    assert r.exit_code == 0 and "saved as" not in r.output
    r = runner.invoke(app, ["run", "-a", "red", "-p", "bad=1", "--no-save", *FAST])
    assert r.exit_code == 2


def test_python_dash_m():
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-m", "bufferlab", "--version"], capture_output=True, text=True
    )
    assert out.returncode == 0 and __version__ in out.stdout


def test_launcher_flag_survives_a_shadowing_bufferlab_directory(tmp_path):
    """Running from a folder that contains a `bufferlab/` dir (e.g. the clone's parent, ~) must still work."""
    import subprocess
    import sys

    (tmp_path / "bufferlab").mkdir()
    out = subprocess.run(
        [sys.executable, "-P", "-m", "bufferlab", "--version"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0 and __version__ in out.stdout


def _fake_measurement():
    from bufferlab.netprobe import probe as pr

    return pr.Measurement(
        "2026-01-01T00:00:00+00:00",
        "1.1.1.1",
        "u",
        "linux",
        pr.PingStats(10, [20.0] * 10),
        pr.PingStats(10, [120.0] * 10),
        20.0,
        1,
    )


def test_network_probe_requires_consent_then_saves(monkeypatch):
    from bufferlab.netprobe import probe as pr

    called = []
    monkeypatch.setattr(pr, "run_probe", lambda *a, **k: called.append(1) or _fake_measurement())
    r = runner.invoke(app, ["network", "probe"], input="n\n")
    assert r.exit_code == 1 and not called  # no traffic without a yes
    r = runner.invoke(app, ["network", "probe"], input="y\n")
    assert r.exit_code == 0 and called and "20.00 Mbps" in r.output
    shown = runner.invoke(app, ["network", "show"])
    assert shown.exit_code == 0 and "Estimated buffer" in shown.output


def test_network_predict_uses_saved_profile_and_saves_runs(monkeypatch):
    from bufferlab.netprobe import probe as pr

    assert runner.invoke(app, ["network", "predict"]).exit_code == 1  # nothing measured yet
    monkeypatch.setattr(pr, "run_probe", lambda *a, **k: _fake_measurement())
    runner.invoke(app, ["network", "probe", "--yes"])
    r = runner.invoke(
        app, ["network", "predict", "--loads", "10,40", "--algorithms", "drop-tail,codel"]
    )
    assert r.exit_code == 0, r.output
    assert "SIMULATED" in r.output and "40.0" in r.output and "codel" in r.output
    assert len(ids(runner.invoke(app, ["history", "--limit", "50"]).output)) == 4


def test_network_predict_manual_and_errors():
    r = runner.invoke(app, ["network", "predict", "--capacity-mbps", "10", "--loads", "5,20"])
    assert r.exit_code == 0 and "loss first exceeds 1%" in r.output
    assert (
        runner.invoke(
            app, ["network", "predict", "--capacity-mbps", "10", "--loads", "x"]
        ).exit_code
        == 2
    )
    assert (
        runner.invoke(
            app, ["network", "predict", "--capacity-mbps", "10", "--algorithms", "nope"]
        ).exit_code
        == 2
    )
