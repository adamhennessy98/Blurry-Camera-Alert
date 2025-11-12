from datetime import datetime, timedelta, timezone, time as dtime

from blurry_mvp import AlertCandidate, SiteAlertAggregator


def make_candidate(camera_id: str, ready_at: datetime, site_id: str = "SiteA") -> AlertCandidate:
    blur_start = ready_at - timedelta(seconds=30)
    return AlertCandidate(
        camera_id=camera_id,
        line_number=1,
        blur_since=blur_start,
        ready_at=ready_at,
        site_id=site_id,
    )


def test_aggregator_dispatches_when_minimum_met():
    now = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    aggregator = SiteAlertAggregator(window_sec=30, min_count=2, suppress_sec=90)
    cand1 = make_candidate("CAM-01", ready_at=now)
    cand2 = make_candidate("CAM-02", ready_at=now)

    aggregator.enqueue(cand1)
    aggregator.enqueue(cand2)
    actions = aggregator.process(now)

    assert len(actions) == 1
    action = actions[0]
    assert action.kind == "aggregate"
    assert {c.camera_id for c in action.candidates} == {"CAM-01", "CAM-02"}
    assert action.washdown_hint is False


def test_aggregator_suppresses_repeated_aggregate_until_cooldown_expires():
    start = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)
    aggregator = SiteAlertAggregator(window_sec=30, min_count=2, suppress_sec=120)
    aggregator.enqueue(make_candidate("CAM-01", ready_at=start))
    aggregator.enqueue(make_candidate("CAM-02", ready_at=start))
    first = aggregator.process(start)
    assert first and first[0].kind == "aggregate"

    later = start + timedelta(seconds=15)
    aggregator.enqueue(make_candidate("CAM-03", ready_at=later))
    aggregator.enqueue(make_candidate("CAM-04", ready_at=later))
    suppressed = aggregator.process(later)
    assert suppressed == []

    after_cooldown = start + timedelta(seconds=130)
    aggregator.enqueue(make_candidate("CAM-05", ready_at=after_cooldown))
    aggregator.enqueue(make_candidate("CAM-06", ready_at=after_cooldown))
    dispatched = aggregator.process(after_cooldown)
    assert dispatched and dispatched[0].kind == "aggregate"


def test_single_alert_emitted_when_window_expires():
    now = datetime(2025, 1, 1, 7, 0, tzinfo=timezone.utc)
    aggregator = SiteAlertAggregator(window_sec=10, min_count=3, suppress_sec=60)
    candidate = make_candidate("CAM-99", ready_at=now)
    aggregator.enqueue(candidate)

    actions = aggregator.process(now + timedelta(seconds=11))

    assert actions and actions[0].kind == "single"
    assert actions[0].candidates[0].camera_id == "CAM-99"


def test_washdown_hint_enabled_when_schedule_matches():
    now = datetime(2025, 1, 1, 5, 0, tzinfo=timezone.utc)
    schedule = [(dtime(0, 0), dtime(23, 59))]
    aggregator = SiteAlertAggregator(window_sec=30, min_count=2, suppress_sec=60, washdown_schedule=schedule)
    aggregator.enqueue(make_candidate("CAM-01", ready_at=now))
    aggregator.enqueue(make_candidate("CAM-02", ready_at=now))

    actions = aggregator.process(now)

    assert actions[0].washdown_hint is True
