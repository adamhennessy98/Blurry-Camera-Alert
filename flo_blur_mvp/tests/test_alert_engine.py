import csv
from datetime import datetime, timedelta, timezone

from blurry_mvp import AlertEngine, BlurEpisodeStore, CameraAlertState


class StubNotifier:
    def alert_single(self, *args, **kwargs):
        return "ignore"

    def alert_aggregate(self, *args, **kwargs):
        return "ignore"


class StubSimulator:
    def __init__(self):
        self.calls = []

    def set_blurry(self, camera_id: str, is_blurry: bool) -> None:
        self.calls.append((camera_id, is_blurry))


def build_engine(tmp_path):
    episodes_path = tmp_path / "episodes.csv"
    store = BlurEpisodeStore(str(episodes_path))
    simulator = StubSimulator()
    engine = AlertEngine(
        notifier=StubNotifier(),
        line_lookup={"CAM-01": 1},
        site_lookup={"CAM-01": "SiteA"},
        simulator=simulator,
        episode_store=store,
        threshold_sec=1,
        suppress_sec=30,
        aggregate_window_sec=5,
        aggregate_min=1,
        aggregate_suppress_sec=10,
        washdown_schedule=None,
    )
    return engine, simulator, episodes_path


def test_after_alert_logs_episode_on_clean(tmp_path):
    engine, simulator, episodes_path = build_engine(tmp_path)
    blur_start = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    resolved_at = blur_start + timedelta(minutes=4)
    state = engine.state.setdefault(
        "CAM-01",
        CameraAlertState(is_blurry=True, blur_start=blur_start, alert_open=True, pending_candidate=True),
    )

    engine._after_alert(resolved_at, ["CAM-01"], "clean")

    with episodes_path.open(newline="") as f:
        rows = list(csv.reader(f))

    assert rows[0] == ["camera_id", "blur_start_iso", "cleared_iso"]
    assert rows[1] == ["CAM-01", blur_start.isoformat(), resolved_at.isoformat()]
    assert simulator.calls == [("CAM-01", False)]
    assert state.is_blurry is False
    assert state.blur_start is None
    assert state.alert_open is False
    assert state.last_alert_until is None
    assert state.pending_candidate is False


def test_after_alert_sets_cooldown_on_ignore(tmp_path):
    engine, simulator, episodes_path = build_engine(tmp_path)
    blur_start = datetime(2025, 1, 1, 8, 0, tzinfo=timezone.utc)
    now = blur_start + timedelta(minutes=1)
    state = engine.state.setdefault(
        "CAM-01",
        CameraAlertState(is_blurry=True, blur_start=blur_start, alert_open=False, pending_candidate=True),
    )

    engine._after_alert(now, ["CAM-01"], "ignore")

    assert state.alert_open is True
    assert state.last_alert_until == now + engine.suppress
    assert state.is_blurry is True
    assert state.blur_start == blur_start
    assert state.pending_candidate is False
    assert simulator.calls == []

    with episodes_path.open(newline="") as f:
        rows = list(csv.reader(f))

    assert rows == [["camera_id", "blur_start_iso", "cleared_iso"]]
