# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Scheduled life events.

A :class:`LifeEvent` runs a callable in a given simulated year. :class:`LifeEvents` holds the
schedule and fires each event during the model's ``events`` stage (see ``LifeModel.STAGES``):
after the year's income has arrived and before the tax units settle the year, so an event's
one-time expense is paid this year, a home bought this year has its sale proceeds and gains taxed
this year, and a marriage, state move or salary change applies to this year's return.

An event can opt into a different stage with ``stage=``: ``"pre_step"`` fires before the year's
income arrives (after ages advance), ``"post_step"`` after the year has been settled (so its effect
starts next year).
"""

import warnings
from collections.abc import Callable
from typing import ClassVar

from .model import Event, LifeModelAgent

#: Stages a life event may fire in.
LIFE_EVENT_STAGES = ("pre_step", "events", "post_step")


class LifeEventRecord(Event):
    """Event-log entry written when a scheduled life event fires.

    A typed stand-in for the richer event model of a later plan: it carries the event's name, the
    year it was scheduled for and the stage it fired in, alongside the usual message.
    """

    def __init__(self, life_event: "LifeEvent", stage: str):
        super().__init__(f"Life event: {life_event.name}")
        self.name = life_event.name
        self.scheduled_year = life_event.year
        self.stage = stage


class LifeEvents(LifeModelAgent):
    # Fire pre_step events after people have aged (-20) and before RMDs (-10) and income (0);
    # post_step events after every year-end reset and escalator.
    STEP_PRIORITY: ClassVar[dict[str, int]] = {"pre_step": -15, "post_step": 10}

    def __init__(self, model, life_events: list["LifeEvent"] | None = None, *, allow_past: bool = False):
        """List of life events

        Args:
            model (LifeModel): LifeModel in which the life events take place.
            life_events (List[LifeEvent], optional): List of life events. Defaults to None.
            allow_past (bool, optional): Events dated before the next simulated year (for a model
                that has not started, before ``start_year``) can never fire on schedule. By default
                they raise ``ValueError``; with ``allow_past=True`` they are applied immediately, at
                construction (the right behaviour for "they got married in 2024"). Note that an
                applied past expense is charged to the first simulated year. Keyword-only.

        Raises:
            ValueError: If an event is dated in the past and ``allow_past`` is False.
        """
        super().__init__(model)
        self.allow_past = allow_past
        self.life_events: list[LifeEvent] = []
        for life_event in [] if life_events is None else life_events:
            self.add(life_event)

    def add(self, life_event: "LifeEvent") -> None:
        """Schedule ``life_event`` (validated exactly like the constructor's events)."""
        if life_event.year < self.model.year:
            if not self.allow_past:
                raise ValueError(
                    f"Life event {life_event.name!r} is dated {life_event.year}, before the simulation's next "
                    f"year {self.model.year}, so it would never fire. Pass allow_past=True to apply past "
                    "events immediately."
                )
            self._fire_one(life_event, stage="construction")
            return
        if life_event.year > self.model.end_year:
            warnings.warn(
                f"Life event {life_event.name!r} is dated {life_event.year}, after the simulation's end year "
                f"{self.model.end_year}; it will not fire.",
                UserWarning,
                stacklevel=2,
            )
        self.life_events.append(life_event)

    def _repr_html_(self):
        table = "<table>"
        table += "<tr><th>Year:</th><th>Event:</th></tr>\n"
        table += "".join(f"<tr><td>{x.year}</td><td>{x.name}</td></tr>\n" for x in self.life_events)
        table += "</table>"
        return table

    def _fire_one(self, life_event: "LifeEvent", stage: str) -> None:
        life_event.event(*life_event.event_args)
        self.model.event_log.add(LifeEventRecord(life_event, stage))

    def _fire_stage(self, stage: str) -> None:
        """Fire this year's events scheduled for ``stage`` and drop them from the schedule."""
        due = [x for x in self.life_events if x.year == self.model.year and x.stage == stage]
        if not due:
            return
        self.life_events = [x for x in self.life_events if x not in due]
        for life_event in due:
            self._fire_one(life_event, stage)

    def pre_step(self):
        self._fire_stage("pre_step")

    def events(self):
        self._fire_stage("events")

    def post_step(self):
        self._fire_stage("post_step")


class LifeEvent:
    def __init__(self, year: int, name: str, event: Callable, *event_args, stage: str = "events"):
        """Life Event.

        Args:
            year (int): Year in which the life event takes place.
            name (str): Name of the event.
            event (Callable): Callable performed at the specified year.
            *event_args: Arguments to pass to the event callable.
            stage (str, optional): Stage the event fires in: ``"events"`` (default; after income,
                before settlement), ``"pre_step"`` (before the year's income arrives) or
                ``"post_step"`` (after settlement; takes effect next year). Keyword-only.
        """
        if stage not in LIFE_EVENT_STAGES:
            raise ValueError(f"Unknown life event stage {stage!r}; expected one of {LIFE_EVENT_STAGES}")
        self.year = year
        self.name = name
        self.event = event
        self.event_args = event_args
        self.stage = stage

    def eval_event(self, year) -> bool:
        """Run the event if it is scheduled for ``year`` (regardless of stage). Returns whether it ran.

        Kept for direct callers; the engine fires events through :class:`LifeEvents`, which also
        logs them.
        """
        if self.year == year:
            self.event(*self.event_args)
            return True
        return False
