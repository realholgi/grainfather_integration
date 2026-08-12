"""Pure, dependency-free helpers deciding the adaptive poll cadence.

These functions intentionally avoid importing Home Assistant (or any other
third-party dependency) so they can be unit-tested in isolation, mirroring the
plain-``pytest`` style used for the API parsing tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from .const import (
    ACTIVE_BREW_SESSION_STATUSES,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

if TYPE_CHECKING:
    from .api import GrainfatherSnapshot

# A fermentation controller heard within this window counts as active.
DEVICE_RECENT_SECONDS = 3600


def _clamp_interval(seconds: int) -> int:
    return max(MIN_SCAN_INTERVAL, min(MAX_SCAN_INTERVAL, seconds))


def is_boost_active(boost_until: datetime | None, now: datetime) -> bool:
    """Return True while a post-action poll boost is still in effect."""
    return boost_until is not None and now < boost_until


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _device_recently_heard(last_heard: str | None, now: datetime) -> bool:
    parsed = _parse_timestamp(last_heard)
    if parsed is None:
        return False
    return (now - parsed).total_seconds() <= DEVICE_RECENT_SECONDS


def snapshot_is_active(
    snapshot: GrainfatherSnapshot,
    *,
    now: datetime | None = None,
) -> bool:
    """Return True when the snapshot reflects an actively brewing/fermenting setup.

    Active means any brew session is brewing/fermenting, or a fermentation
    controller is linked and was heard from recently.
    """
    if now is None:
        now = datetime.now(UTC)

    for session in snapshot.brew_sessions:
        if session.status in ACTIVE_BREW_SESSION_STATUSES:
            return True

    for device in snapshot.fermentation_devices:
        if device.is_controller_linked and _device_recently_heard(
            device.last_heard, now
        ):
            return True

    return False


def compute_update_interval(
    snapshot: GrainfatherSnapshot,
    active_interval: int,
    idle_interval: int,
    *,
    boosted: bool = False,
    now: datetime | None = None,
) -> timedelta:
    """Return the poll interval for the given snapshot, clamped to bounds."""
    active = _clamp_interval(active_interval)
    idle = _clamp_interval(idle_interval)
    if boosted or snapshot_is_active(snapshot, now=now):
        return timedelta(seconds=active)
    return timedelta(seconds=idle)
