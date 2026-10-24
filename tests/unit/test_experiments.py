import csv
import json

import pytest

from bufferlab.analysis.comparison import comparison_rows, observations, sort_rows
from bufferlab.analysis.reporting import FORMATS, export_runs
from bufferlab.experiments.batch import BatchSpec, run_batch
from bufferlab.experiments.models import ExperimentConfig
from bufferlab.experiments.runner import run_experiment
from bufferlab.experiments.scenarios import SCENARIOS, get_scenario, scenario_config
from bufferlab.storage import AmbiguousIdError, NotFoundError, Repository


def quick(**kw):
    base = dict(duration_s=6.0, warmup_s=1.0, offered_load_pct=110.0)
    base.update(kw)
    return ExperimentConfig(**base)


# ---- validation ----
def test_default_config_valid():
    assert ExperimentConfig().validate().ok


@pytest.mark.parametrize(
    "change",
    [
        dict(link_mbps=0),
        dict(link_mbps=-1),
        dict(packet_size_bytes=0),
        dict(queue_capacity=0),
        dict(offered_load_pct=-1),
        dict(n_sources=0),
        dict(duration_s=0),
        dict(warmup_s=-1),
        dict(duration_s=3, warmup_s=3),
        dict(duration_s=3, warmup_s=4),
        dict(seed=-1),
        dict(algorithm="nope"),
        dict(traffic_model="nope"),
        dict(prop_delay_ms=-1),
        dict(algorithm="red", algorithm_params={"min_th": 20, "max_th": 10}),
        dict(algorithm="red", algorithm_params={"bogus": 1}),
        dict(algorithm="codel", algorithm_params={"target_ms": 0}),
    ],
)
def test_invalid_configs_have_errors(change):
    assert not ExperimentConfig(**change).validate().ok


def test_warnings():
    r = ExperimentConfig(duration_s=2.0, warmup_s=1.0, offered_load_pct=0).validate()
    assert r.ok and any("zero offered load" in w.message for w in r.warnings)
    r = ExperimentConfig(offered_load_pct=150).validate()
    assert any("exceeds link capacity" in w.message for w in r.warnings)
    r = ExperimentConfig(algorithm="red", algorithm_params={"min_th": 5, "max_th": 500}).validate()
    assert any("max_th" in w.message for w in r.warnings)


def test_config_roundtrip_and_fingerprint():
    c = quick(algorithm="red", algorithm_params={"max_p": 0.3})
    assert ExperimentConfig.from_dict(c.to_dict()) == c
    assert c.fingerprint() == c.replace(name="other").fingerprint()
    assert c.fingerprint() != c.replace(seed=99).fingerprint()


def test_load_percentage_translates_to_pps():
    c = ExperimentConfig(link_mbps=10, packet_size_bytes=1500, offered_load_pct=50)
    assert c.arrival_rate_pps == pytest.approx(416.6667, rel=1e-5)
    assert c.to_sim_config().offered_bps == pytest.approx(5e6)


def test_scenarios_documented_and_runnable():
    assert len(SCENARIOS) == 8
    assert get_scenario("Heavy Congestion").key == "heavy-congestion"
    with pytest.raises(ValueError):
        get_scenario("nope")
    for s in SCENARIOS.values():
        assert s.description and s.config.validate().ok
    rec = run_experiment(scenario_config("light-traffic", "red", duration_s=5.0, warmup_s=1.0))
    assert rec.config.algorithm == "red" and rec.metrics["generated"] > 0


def test_same_scenario_different_algorithms_actually_differ():
    kw = dict(duration_s=10.0, warmup_s=2.0)
    a = run_experiment(scenario_config("heavy-congestion", "drop-tail", **kw)).metrics
    b = run_experiment(scenario_config("heavy-congestion", "codel", **kw)).metrics
    assert a["dropped_aqm"] == 0 and b["dropped_aqm"] > 0


# ---- batch ----
def test_batch_expand_and_dedupe_params():
    spec = BatchSpec(
        "b", quick(), {"algorithm": ["drop-tail", "red"], "param.max_p": [0.1, 0.5]}, 2
    )
    pts = spec.points()
    # drop-tail ignores param.max_p => single drop-tail point + 2 red points
    assert len(pts) == 3
    assert spec.total_runs() == 6


def test_batch_cancel_and_validation():
    import threading

    ev = threading.Event()
    ev.set()
    res = run_batch(BatchSpec("b", quick(), {}, 2), cancel=ev)
    assert res.cancelled and res.runs == []
    with pytest.raises(ValueError):
        run_batch(BatchSpec("b", quick(), {"queue_capacity": []}, 1))


# ---- storage ----
def test_repository_roundtrip_search_delete(tmp_path):
    repo = Repository(tmp_path / "t.sqlite3")
    r1 = run_experiment(quick(name="alpha", algorithm="red"))
    r2 = run_experiment(quick(name="beta", algorithm="codel"))
    repo.save_run(r1)
    repo.save_run(r2)
    got = repo.get_run(r1.run_id)
    assert got.metrics == r1.metrics and got.series == r1.series and got.config == r1.config
    assert got.software_version and got.schema_version == 1
    assert [r.run_id for r in repo.list_runs(search="beta")] == [r2.run_id]
    assert len(repo.list_runs(algorithm="red")) == 1
    assert repo.get_run(r1.run_id[:6]).run_id == r1.run_id
    with pytest.raises(NotFoundError):
        repo.get_run("zzzz")
    with pytest.raises(AmbiguousIdError):
        repo.get_run("r")
    repo.delete_run(r1.run_id)
    assert repo.count_runs() == 1
    with pytest.raises(NotFoundError):
        repo.get_run(r1.run_id)
    # series cascade-deleted
    assert repo.conn.execute("SELECT COUNT(*) FROM run_series").fetchone()[0] == 1


def test_results_persist_across_restart(tmp_path):
    path = tmp_path / "p.sqlite3"
    r = run_experiment(quick())
    Repository(path).save_run(r)
    again = Repository(path)
    assert again.get_run(r.run_id).metrics == r.metrics


# ---- comparison + export ----
def three_runs():
    return [
        run_experiment(quick(algorithm=a, offered_load_pct=130))
        for a in ("drop-tail", "red", "codel")
    ]


def test_comparison_and_observations():
    runs = three_runs()
    rows = comparison_rows(runs)
    assert [r["tag"] for r in rows] == ["A", "B", "C"]
    s = sort_rows(rows, "loss_rate")
    assert s[0]["loss_rate"] <= s[-1]["loss_rate"]
    obs = observations(runs)
    assert any("packet-loss rate" in o and "under the tested configuration" in o for o in obs)
    assert not any("always" in o.lower() for o in obs)
    assert observations(runs[:1]) == ["Select at least two runs to compare."]


def test_observation_flags_confounders():
    a = run_experiment(quick(algorithm="red"))
    b = run_experiment(quick(algorithm="codel", queue_capacity=10))
    assert any("queue_capacity" in o for o in observations([a, b]))


@pytest.mark.parametrize("fmt", FORMATS)
def test_export_formats(tmp_path, fmt):
    runs = three_runs()
    p = export_runs(runs, fmt, tmp_path / f"out.{fmt}")
    text = p.read_text()
    assert runs[0].run_id in text
    if fmt == "csv":
        rows = list(csv.DictReader(text.splitlines()))
        assert len(rows) == 3
        assert float(rows[0]["m_throughput_mbps"]) == pytest.approx(
            runs[0].metrics["throughput_mbps"]
        )
        assert rows[1]["cfg_algorithm"] == "red" and rows[0]["cfg_seed"] == "42"
    if fmt == "json":
        d = json.loads(text)
        assert d["runs"][2]["metrics"] == runs[2].metrics
        assert d["runs"][0]["config"]["seed"] == 42 and d["bufferlab_version"]
    if fmt in ("md", "txt"):
        assert "Limitations" in text or "LIMITATIONS" in text
        assert "not an independently verified" in text


def test_export_errors(tmp_path):
    with pytest.raises(ValueError):
        export_runs([], "csv", tmp_path / "x.csv")
    with pytest.raises(ValueError):
        export_runs(three_runs()[:1], "xml", tmp_path / "x.xml")
