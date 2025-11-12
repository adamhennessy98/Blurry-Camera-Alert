from datetime import time as dtime

from blurry_mvp import parse_washdown_schedule


def test_parse_washdown_schedule_multiple_windows():
    schedule = parse_washdown_schedule("06:00-06:30,18:00-18:30")
    assert schedule == [(dtime(6, 0), dtime(6, 30)), (dtime(18, 0), dtime(18, 30))]


def test_parse_washdown_schedule_wraps_midnight():
    schedule = parse_washdown_schedule("23:00-01:00")
    assert schedule == [(dtime(23, 0), dtime(1, 0))]


def test_parse_washdown_schedule_reports_errors(capfd):
    schedule = parse_washdown_schedule("invalid")
    captured = capfd.readouterr()
    assert "Could not parse washdown window" in captured.out
    assert schedule == []
