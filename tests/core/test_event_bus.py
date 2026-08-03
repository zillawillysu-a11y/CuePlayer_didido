"""Unit tests for the in-process EventBus (infrastructure only)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from cueplayer.core import EventBus
from cueplayer.core.event_bus import EventBus as EventBusDirect


@dataclass(frozen=True)
class _MarkDirty:
    reason: str = ""


@dataclass(frozen=True)
class _SongActivated:
    index: int


def test_publish_delivers_to_subscriber() -> None:
    bus = EventBus()
    seen: list[_MarkDirty] = []
    bus.subscribe(_MarkDirty, seen.append)
    event = _MarkDirty("edit")
    bus.publish(event)
    assert seen == [event]


def test_multiple_handlers_preserve_subscription_order() -> None:
    bus = EventBus()
    order: list[str] = []
    bus.subscribe(_MarkDirty, lambda e: order.append("a"))
    bus.subscribe(_MarkDirty, lambda e: order.append("b"))
    bus.publish(_MarkDirty())
    assert order == ["a", "b"]


def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    seen: list[_MarkDirty] = []
    bus.subscribe(_MarkDirty, seen.append)
    bus.unsubscribe(_MarkDirty, seen.append)
    bus.publish(_MarkDirty("x"))
    assert seen == []


def test_unsubscribe_unknown_is_noop() -> None:
    bus = EventBus()
    bus.unsubscribe(_MarkDirty, lambda e: None)
    bus.publish(_MarkDirty())


def test_duplicate_subscribe_ignored() -> None:
    bus = EventBus()
    seen: list[_MarkDirty] = []
    bus.subscribe(_MarkDirty, seen.append)
    bus.subscribe(_MarkDirty, seen.append)
    bus.publish(_MarkDirty())
    assert len(seen) == 1


def test_event_types_are_isolated() -> None:
    bus = EventBus()
    dirty: list[_MarkDirty] = []
    songs: list[_SongActivated] = []
    bus.subscribe(_MarkDirty, dirty.append)
    bus.subscribe(_SongActivated, songs.append)
    bus.publish(_MarkDirty("a"))
    bus.publish(_SongActivated(2))
    assert len(dirty) == 1 and dirty[0].reason == "a"
    assert songs == [_SongActivated(2)]


def test_publish_with_no_subscribers_is_noop() -> None:
    bus = EventBus()
    bus.publish(_MarkDirty())


def test_handler_exception_stops_later_handlers() -> None:
    bus = EventBus()
    order: list[str] = []

    def boom(_event: _MarkDirty) -> None:
        order.append("boom")
        raise RuntimeError("fail")

    bus.subscribe(_MarkDirty, boom)
    bus.subscribe(_MarkDirty, lambda e: order.append("after"))
    with pytest.raises(RuntimeError, match="fail"):
        bus.publish(_MarkDirty())
    assert order == ["boom"]


def test_exact_type_match_only_no_inheritance() -> None:
    bus = EventBus()
    seen: list[object] = []

    class Base:
        pass

    class Child(Base):
        pass

    bus.subscribe(Base, seen.append)
    bus.publish(Child())
    assert seen == []


def test_package_export_matches_module() -> None:
    assert EventBus is EventBusDirect
