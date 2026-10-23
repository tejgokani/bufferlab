import pytest

from bufferlab.experiments.scenarios import scenario_config
from bufferlab.storage import Repository
from bufferlab.tui.app import BufferLabApp
from bufferlab.tui.keymap import NAV

pytestmark = pytest.mark.asyncio


async def settle(pilot, app, until, timeout=60):
    for _ in range(timeout * 20):
        await pilot.pause(0.05)
        if until():
            return
    raise AssertionError("timed out")


async def test_launch_and_navigate_all_screens(tmp_path):
    app = BufferLabApp(Repository(tmp_path / "t.db"))
    async with app.run_test(size=(120, 40)) as pilot:
        assert app.current_name() == "dashboard"
        for n in NAV:
            await pilot.press(n.key)
            await pilot.pause(0.1)
            assert app.current_name() == n.screen, n
        await pilot.press("f2")
        assert app.current_name() == "dashboard"


async def test_nav_keys_unique():
    keys = [n.key for n in NAV]
    assert len(keys) == len(set(keys))
    assert len({n.screen for n in NAV}) == len(NAV)


async def test_dashboard_empty_state_then_live_run(tmp_path):
    app = BufferLabApp(Repository(tmp_path / "t.db"))
    async with app.run_test(size=(120, 40)) as pilot:
        empty = app.screen.query_one("#empty-state").content
        assert "No simulation has been run yet" in str(empty)
        cfg = scenario_config("heavy-congestion", "codel", duration_s=10.0, warmup_s=2.0)
        assert app.start_run(cfg)
        await settle(pilot, app, lambda: app.state.status == "done")
        assert app.repo.count_runs() == 1
        card = str(app.screen.query_one("#c-thr").content)
        assert "Mbps" in card
        assert app.state.record.run_id == app.focus_run_id


async def test_invalid_config_rejected_with_message(tmp_path):
    app = BufferLabApp(Repository(tmp_path / "t.db"))
    async with app.run_test(size=(120, 40)):
        bad = scenario_config("light-traffic", "drop-tail", duration_s=5.0, warmup_s=5.0)
        assert not app.start_run(bad)
        assert app.state.status == "idle"


async def test_cancel_running_simulation(tmp_path):
    app = BufferLabApp(Repository(tmp_path / "t.db"))
    async with app.run_test(size=(120, 40)) as pilot:
        cfg = scenario_config("high-bandwidth", "drop-tail", duration_s=60.0, warmup_s=1.0)
        app.start_run(cfg)
        await pilot.pause(0.5)
        await pilot.press("escape")
        await settle(pilot, app, lambda: app.state.status == "cancelled")
        assert app.repo.count_runs() == 0


async def test_new_experiment_form_validates_and_runs(tmp_path):
    app = BufferLabApp(Repository(tmp_path / "t.db"))
    async with app.run_test(size=(120, 50)) as pilot:
        await pilot.press("f3")
        await pilot.pause(0.2)
        scr = app.screen
        scr.query_one("#f-warmup_s").value = "100"
        scr.query_one("#f-duration_s").value = "30"
        await pilot.pause(0.2)
        summary = str(scr.query_one("#summary").content)
        assert "warm-up" in summary.lower() and "must be shorter" in summary
        scr.query_one("#f-warmup_s").value = "3"
        scr.query_one("#f-duration_s").value = "10"
        scr.query_one("#f-queue_capacity").value = "abc"
        await pilot.pause(0.2)
        assert "not a valid" in str(scr.query_one("#summary").content)
        scr.query_one("#f-queue_capacity").value = "40"
        await pilot.pause(0.2)
        assert "Configuration is valid" in str(scr.query_one("#summary").content) or "Valid" in str(
            scr.query_one("#summary").render()
        )
        await pilot.press("ctrl+r")
        await settle(pilot, app, lambda: app.state.status == "done")
        assert app.state.record.config.queue_capacity == 40
        assert app.current_name() == "dashboard"


async def test_full_flow_run_history_compare_export(tmp_path):
    app = BufferLabApp(Repository(tmp_path / "t.db"))
    async with app.run_test(size=(140, 45)) as pilot:
        for alg in ("drop-tail", "codel"):
            app.start_run(scenario_config("heavy-congestion", alg, duration_s=8.0, warmup_s=2.0))
            await settle(pilot, app, lambda: app.state.status == "done")
            app.state.status = "idle"
        await pilot.press("f5")
        await pilot.pause(0.3)
        h = app.screen
        assert len(h.runs) == 2
        await pilot.press("space", "down", "space")
        assert len(app.selected_runs) == 2
        await pilot.press("c")
        await pilot.pause(0.3)
        assert app.current_name() == "compare"
        view = app.screen.query_one("#view").content
        import io

        from rich.console import Console

        con = Console(width=140, record=True, file=io.StringIO())
        con.print(view)
        text = con.export_text()
        assert "Observations" in text and "drop-tail" in text and "codel" in text
        await pilot.press("s")  # cycle sort
        await pilot.press("f6")
        await pilot.pause(0.3)
        ex = app.screen
        ex.query_one("#path").value = str(tmp_path / "out.csv")
        await pilot.press("ctrl+e")
        await pilot.pause(0.3)
        assert (tmp_path / "out.csv").exists()
        assert "wrote" in str(ex.query_one("#msg").content)


async def test_delete_requires_confirmation(tmp_path):
    app = BufferLabApp(Repository(tmp_path / "t.db"))
    async with app.run_test(size=(120, 40)) as pilot:
        app.start_run(scenario_config("light-traffic", "red", duration_s=5.0, warmup_s=1.0))
        await settle(pilot, app, lambda: app.state.status == "done")
        await pilot.press("f5")
        await pilot.pause(0.3)
        await pilot.press("d")
        await pilot.pause(0.2)
        await pilot.press("n")
        await pilot.pause(0.2)
        assert app.repo.count_runs() == 1
        await pilot.press("d")
        await pilot.pause(0.2)
        await pilot.press("y")
        await pilot.pause(0.3)
        assert app.repo.count_runs() == 0


async def test_scenario_library_runs_all_algorithms_and_opens_compare(tmp_path):
    app = BufferLabApp(Repository(tmp_path / "t.db"))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("f7")
        await pilot.pause(0.3)
        app.screen.action_run_all()
        await settle(pilot, app, lambda: app.current_name() == "compare", timeout=120)
        assert app.repo.count_runs() == 3
        assert len(app.selected_runs) == 3


async def test_research_mode_generates_report(tmp_path):
    app = BufferLabApp(Repository(tmp_path / "t.db"))
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.press("f10")
        await pilot.pause(0.3)
        s = app.screen
        s.query_one("#loads").value = "60,140"
        s.query_one("#caps").value = "10"
        s.query_one("#reps").value = "2"
        s.query_one("#dur").value = "6"
        s.query_one("#warm").value = "1"
        await pilot.pause(0.2)
        assert "6 points" in str(s.query_one("#plan").content)
        await pilot.press("ctrl+r")
        await settle(pilot, app, lambda: app.current_name() == "research", timeout=120)
        assert app.repo.count_runs() == 12
        assert app.last_batch is not None
        await pilot.press("ctrl+w")
        await pilot.pause(0.3)
        assert any(
            p.name.startswith("research-")
            for p in __import__("bufferlab.utils.paths", fromlist=["x"]).exports_dir().iterdir()
        )


async def test_contextual_help_and_quit_behaviour(tmp_path):
    app = BufferLabApp(Repository(tmp_path / "t.db"))
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.press("f5")
        await pilot.press("question_mark")
        await pilot.pause(0.2)
        assert app.screen.__class__.__name__ == "TextModal"
        await pilot.press("escape")
        await pilot.pause(0.1)
        await pilot.press("q")  # not on dashboard: go back
        await pilot.pause(0.1)
        assert app.current_name() == "dashboard"


async def test_80_column_terminal_and_ascii_mode(tmp_path):
    app = BufferLabApp(Repository(tmp_path / "t.db"))
    app.settings["ascii"] = True
    async with app.run_test(size=(80, 30)) as pilot:
        app.start_run(scenario_config("heavy-congestion", "red", duration_s=6.0, warmup_s=1.0))
        await settle(pilot, app, lambda: app.state.status == "done")
        for key in ("f3", "f5", "f2"):
            await pilot.press(key)
            await pilot.pause(0.1)
        chart = app.screen.query_one("#ch-q")
        rendered = str(chart.render())
        assert all(ch not in rendered for ch in "▁▂▃▄▅▆▇█")


async def test_command_palette_lists_every_screen(tmp_path):
    app = BufferLabApp(Repository(tmp_path / "t.db"))
    async with app.run_test(size=(100, 40)):
        titles = {c.title for c in app.get_system_commands(app.screen)}
        for n in NAV:
            assert f"Go to {n.label}" in titles
