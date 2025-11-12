import csv
from datetime import datetime, timezone

import blurry_mvp


class SequenceSimulator:
    def __init__(self, camera_ids, states):
        self.camera_ids = camera_ids
        self.states = [dict(state) for state in states]
        self.index = 0
        self.current_state = {cid: False for cid in camera_ids}

    def tick(self):
        if self.index < len(self.states):
            self.current_state.update(self.states[self.index])
        self.index += 1
        return dict(self.current_state)

    def set_blurry(self, camera_id: str, is_blurry: bool) -> None:
        self.current_state[camera_id] = is_blurry


class DeterministicNotifier:
    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.calls = []

    def alert_single(self, *, camera_label, line_number, blur_since):
        self.calls.append(("single", camera_label, line_number, blur_since))
        return self.decisions.pop(0)

    def alert_aggregate(self, *, site_id, candidates, washdown_hint=False):
        self.calls.append(("aggregate", site_id, len(candidates), washdown_hint))
        return self.decisions.pop(0)


def test_run_writes_event_and_episode_csv(tmp_path, monkeypatch):
    event_path = tmp_path / "events.csv"
    episode_path = tmp_path / "episodes.csv"

    simulator = SequenceSimulator(["CAM-01"], [{"CAM-01": True}])
    notifier = DeterministicNotifier(["clean"])

    monkeypatch.setattr(blurry_mvp.signal, "signal", lambda *args, **kwargs: None)
    monkeypatch.setattr(blurry_mvp.time, "sleep", lambda *args, **kwargs: None)

    blurry_mvp.run(
        cameras=1,
        interval=0,
        csv_path=str(event_path),
        episodes_csv=str(episode_path),
        alert_threshold=0,
        suppress_seconds=1,
        site_id="SiteA",
        aggregate_window=0,
        aggregate_min=1,
        aggregate_suppress=5,
        washdown_schedule=[],
        max_ticks=1,
        simulator=simulator,
        notifier=notifier,
    )

    with event_path.open(newline="") as f:
        events = list(csv.reader(f))

    assert events[0] == ["ts_iso", "camera_id", "is_blurry"]
    assert events[1][1:] == ["CAM-01", "1"]

    with episode_path.open(newline="") as f:
        episodes = list(csv.reader(f))

    assert episodes[0] == ["camera_id", "blur_start_iso", "cleared_iso"]
    assert episodes[1][0] == "CAM-01"

    assert notifier.calls and notifier.calls[0][0] in {"single", "aggregate"}
