from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from custom_components.grainfather.const import (
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from custom_components.grainfather.polling import (
    DEVICE_RECENT_SECONDS,
    compute_update_interval,
    is_boost_active,
    snapshot_is_active,
)

NOW = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)


def _session(status):
    return SimpleNamespace(status=status)


def _device(*, is_controller_linked=False, last_heard=None):
    return SimpleNamespace(
        is_controller_linked=is_controller_linked,
        last_heard=last_heard,
    )


def _snapshot(sessions=(), devices=()):
    return SimpleNamespace(
        brew_sessions=tuple(sessions),
        fermentation_devices=tuple(devices),
    )


def test_snapshot_is_active_when_session_brewing() -> None:
    snapshot = _snapshot(sessions=[_session(10)])

    assert snapshot_is_active(snapshot, now=NOW) is True


def test_snapshot_is_active_when_session_fermenting() -> None:
    snapshot = _snapshot(sessions=[_session(20)])

    assert snapshot_is_active(snapshot, now=NOW) is True


def test_snapshot_is_active_when_controller_recently_heard() -> None:
    recent = (NOW - timedelta(minutes=5)).isoformat()
    snapshot = _snapshot(
        devices=[_device(is_controller_linked=True, last_heard=recent)]
    )

    assert snapshot_is_active(snapshot, now=NOW) is True


def test_snapshot_is_inactive_when_controller_heard_long_ago() -> None:
    stale = (NOW - timedelta(hours=5)).isoformat()
    snapshot = _snapshot(
        devices=[_device(is_controller_linked=True, last_heard=stale)]
    )

    assert snapshot_is_active(snapshot, now=NOW) is False


def test_snapshot_is_inactive_when_controller_not_linked() -> None:
    recent = (NOW - timedelta(minutes=5)).isoformat()
    snapshot = _snapshot(
        devices=[_device(is_controller_linked=False, last_heard=recent)]
    )

    assert snapshot_is_active(snapshot, now=NOW) is False


def test_snapshot_is_inactive_for_completed_sessions() -> None:
    snapshot = _snapshot(sessions=[_session(30), _session(35), _session(40)])

    assert snapshot_is_active(snapshot, now=NOW) is False


def test_snapshot_is_inactive_when_empty() -> None:
    assert snapshot_is_active(_snapshot(), now=NOW) is False


def test_snapshot_is_inactive_with_unparseable_last_heard() -> None:
    snapshot = _snapshot(
        devices=[_device(is_controller_linked=True, last_heard="not-a-date")]
    )

    assert snapshot_is_active(snapshot, now=NOW) is False


def test_compute_interval_active_for_active_snapshot() -> None:
    snapshot = _snapshot(sessions=[_session(20)])

    interval = compute_update_interval(snapshot, 60, 300, now=NOW)

    assert interval == timedelta(seconds=60)


def test_compute_interval_idle_for_inactive_snapshot() -> None:
    snapshot = _snapshot(sessions=[_session(40)])

    interval = compute_update_interval(snapshot, 60, 300, now=NOW)

    assert interval == timedelta(seconds=300)


def test_compute_interval_active_when_boosted_even_if_inactive() -> None:
    snapshot = _snapshot(sessions=[_session(40)])

    interval = compute_update_interval(snapshot, 60, 300, boosted=True, now=NOW)

    assert interval == timedelta(seconds=60)


def test_compute_interval_clamps_below_minimum() -> None:
    snapshot = _snapshot(sessions=[_session(20)])

    interval = compute_update_interval(snapshot, 5, 300, now=NOW)

    assert interval == timedelta(seconds=MIN_SCAN_INTERVAL)


def test_compute_interval_clamps_above_maximum() -> None:
    snapshot = _snapshot(sessions=[_session(40)])

    interval = compute_update_interval(snapshot, 60, 100000, now=NOW)

    assert interval == timedelta(seconds=MAX_SCAN_INTERVAL)


def test_compute_interval_idle_for_empty_snapshot() -> None:
    interval = compute_update_interval(_snapshot(), 60, 300, now=NOW)

    assert interval == timedelta(seconds=300)


def test_is_boost_active_before_expiry() -> None:
    boost_until = NOW + timedelta(seconds=30)

    assert is_boost_active(boost_until, NOW) is True


def test_is_boost_active_at_expiry_is_false() -> None:
    assert is_boost_active(NOW, NOW) is False


def test_is_boost_active_after_expiry_is_false() -> None:
    boost_until = NOW - timedelta(seconds=1)

    assert is_boost_active(boost_until, NOW) is False


def test_is_boost_active_when_never_set() -> None:
    assert is_boost_active(None, NOW) is False


def test_snapshot_active_at_device_recent_boundary() -> None:
    boundary = (NOW - timedelta(seconds=DEVICE_RECENT_SECONDS)).isoformat()
    snapshot = _snapshot(
        devices=[_device(is_controller_linked=True, last_heard=boundary)]
    )

    assert snapshot_is_active(snapshot, now=NOW) is True


def test_snapshot_inactive_just_past_device_recent_boundary() -> None:
    stale = (NOW - timedelta(seconds=DEVICE_RECENT_SECONDS + 1)).isoformat()
    snapshot = _snapshot(
        devices=[_device(is_controller_linked=True, last_heard=stale)]
    )

    assert snapshot_is_active(snapshot, now=NOW) is False


def test_snapshot_active_with_naive_last_heard_assumed_utc() -> None:
    naive = (NOW - timedelta(minutes=5)).replace(tzinfo=None).isoformat()
    snapshot = _snapshot(
        devices=[_device(is_controller_linked=True, last_heard=naive)]
    )

    assert snapshot_is_active(snapshot, now=NOW) is True


def test_snapshot_active_with_zulu_last_heard() -> None:
    zulu = (NOW - timedelta(minutes=5)).replace(tzinfo=None).isoformat() + "Z"
    snapshot = _snapshot(
        devices=[_device(is_controller_linked=True, last_heard=zulu)]
    )

    assert snapshot_is_active(snapshot, now=NOW) is True


def test_snapshot_active_with_mixed_sessions() -> None:
    snapshot = _snapshot(
        sessions=[_session(40), _session(30), _session(20), _session(35)]
    )

    assert snapshot_is_active(snapshot, now=NOW) is True


def test_snapshot_inactive_with_none_status_session() -> None:
    snapshot = _snapshot(sessions=[_session(None)])

    assert snapshot_is_active(snapshot, now=NOW) is False
