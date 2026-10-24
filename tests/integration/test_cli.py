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
        "batch",
        "research",
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


def test_batch_and_batch_export(tmp_path):
    r = runner.invoke(
        app,
        [
            "batch",
            "-s",
            "light-traffic",
            "--vary",
            "algorithm=drop-tail,red",
            "--vary",
            "queue_capacity=5,20",
            "--reps",
            "2",
            *FAST,
            "--report",
            str(tmp_path / "r.md"),
        ],
    )
    assert r.exit_code == 0, r.output
    assert (tmp_path / "r.md").read_text().startswith("# BufferLab experiment report")
    bid = [
        w
        for w in r.output.split()
        if w.startswith("b")
        and len(w) == 9
        and w[1:].isalnum()
        and all(c in "0123456789abcdef" for c in w[1:])
    ][-1]
    e = runner.invoke(app, ["export", "--batch", bid, "-f", "md", "-o", str(tmp_path / "x.md")])
    assert e.exit_code == 0 and (tmp_path / "x.md").exists()
    assert len(ids(runner.invoke(app, ["history", "--limit", "50"]).output)) == 8


def test_research_command(tmp_path):
    r = runner.invoke(
        app,
        [
            "research",
            "--loads",
            "60,140",
            "--capacities",
            "10",
            "--algorithms",
            "drop-tail,codel",
            "--reps",
            "2",
            *FAST,
            "--no-save",
        ],
    )
    assert r.exit_code == 0, r.output
    assert (
        "4 points" not in r.output
        and "2 replication" in r.output.replace("(s)", "")
        or "runs" in r.output
    )


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
    out = subprocess.run([sys.executable, "-P", "-m", "bufferlab", "--version"], cwd=tmp_path,
                         capture_output=True, text=True)
    assert out.returncode == 0 and __version__ in out.stdout
