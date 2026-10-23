"""Event kinds for the discrete-event simulator.

The numeric value of an :class:`EventKind` is the tie-break priority for events
that occur at exactly the same simulated timestamp: lower values are processed
first.  Departures are processed before arrivals so that a buffer slot freed at
time *t* is available to a packet arriving at the same *t*.  Remaining ties are
broken by insertion order (FIFO), which keeps runs deterministic.
"""

from __future__ import annotations

from enum import IntEnum


class EventKind(IntEnum):
    DEPARTURE = 0  # a packet finishes transmission on the bottleneck link
    ARRIVAL = 1  # a source emits a packet toward the queue
