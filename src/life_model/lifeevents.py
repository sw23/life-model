# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

"""Scheduled life events.

A :class:`LifeEvent` runs a callable in a given simulated month: ``year`` and ``month`` (default:
the first simulated month of that year, i.e. January, or the start month of a part-year first
year). :class:`LifeEvents` holds the schedule and fires each event during that month's ``events``
stage (see ``LifeModel.STAGES``): after the month's income has arrived and before its bills are
paid, so an event's one-time expense is paid that month, a home bought that month is paid for from
then on and its sale gains are taxed with the year's return, and a marriage, state move or salary
change applies from that month (and to the year's return).

An event can opt into a different stage with ``stage=``: ``"pre_step"`` fires before the month's
income arrives, ``"post_step"`` after the month's bills have been paid (so its effect starts next
month).
"""

import warnings
from collections.abc import Callable
from typing import ClassVar

from .model import Event, EventKind, LifeModelAgent

#: Stages a life event may fire in.
LIFE_EVENT_STAGES = ("pre_step", "events", "post_step")


class LifeEventRecord(Event):
    """Event-log entry written when a scheduled life event fires.

    A typed stand-in for the richer event model of a later plan: it carries the event's name, the
    year (and month, when one was given) it was scheduled for and the stage it fired in, alongside the
    usual message.
    """

    def __init__(self, life_event: "LifeEvent", stage: str):
        super().__init__(EventKind.LIFE_EVENT_FIRED, message=f"Life event: {life_event.name}", stage=stage)
        self.name = life_event.name
        self.scheduled_year = life_event.year
        self.scheduled_month = life_event.month
        self.stage = stage


class LifeEvents(LifeModelAgent):
    # Fire pre_step events before RMDs (-10) and income (0); post_step events after the rest of the
    # month's post_step.
    STEP_PRIORITY: ClassVar[dict[str, int]] = {"pre_step": -15, "post_step": 10}
    MONTHLY = True

    def __init__(self, model, life_events: list["LifeEvent"] | None = None, *, allow_past: bool = False):
        """List of life events

        Args:
            model (LifeModel): LifeModel in which the life events take place.
            life_events (List[LifeEvent], optional): List of life events. Defaults to None.
            allow_past (bool, optional): Events dated before the next simulated month (for a model
                that has not started, before its first month) can never fire on schedule. By default
                they raise ``ValueError``; with ``allow_past=True`` they are applied immediately, at
                construction (the right behaviour for "they got married in 2024"). Note that an
                applied past expense is charged to the first simulated month. Keyword-only.

        Raises:
            ValueError: If an event is dated in the past and ``allow_past`` is False.
        """
        super().__init__(model)
        self.allow_past = allow_past
        self.life_events: list[LifeEvent] = []
        for life_event in [] if life_events is None else life_events:
            self.add(life_event)

    def due_month(self, life_event: "LifeEvent") -> int:
        """The month ``life_event`` fires in: its own ``month``, else the first simulated month of its
        year (January, or the start month of a part-year first year)."""
        if life_event.month is not None:
            return life_event.month
        return self.model.start_month if life_event.year == self.model.start_year else 1

    def add(self, life_event: "LifeEvent") -> None:
        """Schedule ``life_event`` (validated exactly like the constructor's events)."""
        if (life_event.year, self.due_month(life_event)) < (self.model.year, self.model.month):
            if not self.allow_past:
                when = life_event.year if life_event.month is None else f"{life_event.year}-{life_event.month:02d}"
                raise ValueError(
                    f"Life event {life_event.name!r} is dated {when}, before the simulation's next "
                    f"month {self.model.year}-{self.model.month:02d}, so it would never fire. Pass "
                    "allow_past=True to apply past events immediately."
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
        """Fire this month's events scheduled for ``stage`` and drop them from the schedule."""
        year, month = self.model.year, self.model.month
        due = [x for x in self.life_events if x.year == year and x.stage == stage and self.due_month(x) == month]
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
    def __init__(
        self, year: int, name: str, event: Callable, *event_args, stage: str = "events", month: int | None = None
    ):
        """Life Event.

        Args:
            year (int): Year in which the life event takes place.
            name (str): Name of the event.
            event (Callable): Callable performed at the specified year.
            *event_args: Arguments to pass to the event callable.
            stage (str, optional): Stage the event fires in: ``"events"`` (default; after the month's
                income, before its bills), ``"pre_step"`` (before the month's income arrives) or
                ``"post_step"`` (after the month's bills; takes effect next month). Keyword-only.
            month (int, optional): Month (1-12) the event fires in. Defaults to the first simulated
                month of ``year`` (January, or the start month of a part-year first year).
                Keyword-only.
        """
        if stage not in LIFE_EVENT_STAGES:
            raise ValueError(f"Unknown life event stage {stage!r}; expected one of {LIFE_EVENT_STAGES}")
        if month is not None and not 1 <= int(month) <= 12:
            raise ValueError(f"Life event month must be 1-12, got {month}")
        self.month = None if month is None else int(month)
        self.year = year
        self.name = name
        self.event = event
        self.event_args = event_args
        self.stage = stage

    def eval_event(self, year, *, model=None) -> bool:
        """Run the event if it is scheduled for ``year`` (regardless of stage). Returns whether it ran.

        Kept for direct callers; the engine fires events through :class:`LifeEvents`, which also
        logs them. Pass ``model`` (keyword-only) to log the firing on its event log too.
        """
        if self.year == year:
            self.event(*self.event_args)
            if model is not None:
                model.event_log.add(LifeEventRecord(self, getattr(model, "current_stage", None) or "direct"))
            return True
        return False
