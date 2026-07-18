"""Anti-farming property, verified on the pure logic alone (no Discord, no I/O).

Composes decay, per-person diminishing returns and watering into a simulation of
messages over time. It demonstrates the mechanism-design goal: a single person
flooding a channel cannot keep the plant alive, while genuine activity spread
across several people can.
"""

from moisture import (
    DRY_MAX,
    WITHERED_MAX,
    Stage,
    decay,
    next_watering,
    stage,
    water,
)

DAY = 24 * 60 * 60


def _simulate(events: list[tuple[float, int]]) -> float:
    """Replay watering ``events`` — ``(timestamp, person_id)`` sorted by time —
    and return the resulting moisture, decayed to the last event."""
    moisture = 0.0
    windows: dict[int, tuple[float | None, int]] = {}
    last = events[0][0]
    for timestamp, person in events:
        moisture = decay(moisture, timestamp - last)
        start, count = windows.get(person, (None, 0))
        amount, start, count = next_watering(start, count, timestamp)
        windows[person] = (start, count)
        moisture = water(moisture, amount)
        last = timestamp
    return moisture


def _flood(person: int, per_day: int, days: int) -> list[tuple[float, int]]:
    """One person sending ``per_day`` messages a day for ``days`` days."""
    step = DAY / per_day
    return [(day * DAY + i * step, person) for day in range(days) for i in range(per_day)]


def test_single_flooder_cannot_keep_plant_alive() -> None:
    """A lone person spamming ~720 messages/day for a week still ends withered."""
    events = _flood(person=1, per_day=720, days=7)
    final = _simulate(events)
    assert stage(final) is Stage.WITHERED
    assert final < WITHERED_MAX


def test_active_crowd_keeps_plant_healthy() -> None:
    """Six people at a modest ~48 messages/day each lift the plant to healthy."""
    events: list[tuple[float, int]] = []
    for person in range(2, 8):  # six distinct people
        events += _flood(person=person, per_day=48, days=7)
    events.sort()
    final = _simulate(events)
    assert stage(final) is Stage.HEALTHY
    assert final > DRY_MAX


def test_crowd_beats_flooder_despite_fewer_messages() -> None:
    """The crowd wins on moisture even though the flooder sent more messages."""
    flooder_events = _flood(person=1, per_day=720, days=7)  # 5040 messages
    crowd_events: list[tuple[float, int]] = []
    for person in range(2, 8):
        crowd_events += _flood(person=person, per_day=48, days=7)  # 2016 messages
    crowd_events.sort()

    assert len(flooder_events) > len(crowd_events)
    assert _simulate(crowd_events) > _simulate(flooder_events)
