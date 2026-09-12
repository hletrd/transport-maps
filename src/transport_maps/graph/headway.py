"""Expected wait for a scheduled service, shared by every mode that has one.

This arithmetic lived in `graph/air.py` and was air-specific only by accident:
"how long until the next departure" has nothing to do with aeroplanes. Ferries
need exactly the same answer, and the alternative -- having `graph/ferry.py`
import `graph/air.py` -- would be the first import between two mode modules in
this package. Air, rail and ferry currently know nothing about each other, and
that is worth keeping.

It does NOT live in `graph/transfers.py`, the other mode-agnostic candidate,
because `transfers` imports `air.Calibration` and `air` would then have to
import `transfers` back.
"""

MINUTES_PER_WEEK = 7 * 24 * 60
# Sentinel weight for a route with no service. Large but finite so Dijkstra
# never selects it while still keeping the matrix free of infinities.
NO_SERVICE = 10**7


def expected_wait_min(departures_per_week: float) -> int:
    """"Leave now" semantics: expected wait is half the headway.

    A traveller who sets out without consulting a timetable arrives at a
    uniformly random point in the interval between departures, so the mean
    wait is half of it. That is the whole reason for the 0.5 below, and it is
    written here rather than left as a bare factor at the call site.
    """
    if departures_per_week <= 0:
        return NO_SERVICE
    headway = MINUTES_PER_WEEK / departures_per_week
    return round(headway / 2.0)
