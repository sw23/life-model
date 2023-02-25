# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

from typing import Optional, List, Callable
from .model import LifeModelAgent


class LifeEvents(LifeModelAgent):
    def __init__(self, model, life_events: Optional[List['LifeEvent']] = None):
        """List of life events

        Args:
            model (LifeModel): LifeModel in which the life events take place.
            life_events (List[LifeEvent], optional): List of life events. Defaults to None.
        """
        super().__init__(model)
        self.life_events = [] if life_events is None else life_events

    def _repr_html_(self):
        table = "<table>"
        table += "<tr><th>Year:</th><th>Event:</th></tr>\n"
        table += "".join(f"<tr><td>{x.year}</td><td>{x.name}</td></tr>\n" for x in self.life_events)
        table += "</table>"
        return table

    def step(self):
        # Perform life events for the current year (if any)
        self.life_events = [x for x in self.life_events if not x.eval_event(self.model.year)]


class LifeEvent():
    def __init__(self, year: int, name: str, event: Callable, *event_args):
        """Life Event.

        Args:
            year (int): Year in which the life event takes place.
            name (str): Name of the event.
            event (Callable): Callable performed at the specified year.
            *event_args: Arguments to pass to the event callable.
        """
        self.year = year
        self.name = name
        self.event = event
        self.event_args = event_args

    def eval_event(self, year):
        if self.year == year:
            self.event(*self.event_args)
            return True
        return False
