import csv
from datetime import datetime, timedelta, timezone

from blurry_mvp import BlurEpisodeStore, CsvStore, Event


def test_csv_store_appends_with_header(tmp_path):
    path = tmp_path / "events.csv"
    store = CsvStore(str(path))
    ts = datetime(2025, 1, 1, 6, 0, tzinfo=timezone.utc)
    store.append(Event(ts=ts, camera_id="CAM-01", is_blurry=True))

    with path.open(newline="") as f:
        rows = list(csv.reader(f))

    assert rows[0] == ["ts_iso", "camera_id", "is_blurry"]
    assert rows[1] == [ts.isoformat(), "CAM-01", "1"]


def test_blur_episode_store_records_interval(tmp_path):
    path = tmp_path / "episodes.csv"
    store = BlurEpisodeStore(str(path))
    start = datetime(2025, 1, 1, 6, 0, tzinfo=timezone.utc)
    end = start + timedelta(minutes=2)

    store.append("CAM-07", start, end)

    with path.open(newline="") as f:
        rows = list(csv.reader(f))

    assert rows[0] == ["camera_id", "blur_start_iso", "cleared_iso"]
    assert rows[1] == ["CAM-07", start.isoformat(), end.isoformat()]
