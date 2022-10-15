from .basemodel import BaseModel


class LifeEvents(BaseModel):
    def __init__(self, simulation, life_events=None):
        """List of life events

        Args:
            simulation (Simulation): Simulation in which the life events take place.
            life_events (List[LifeEvent], optional): List of life events. Defaults to None.
        """
        self.simulation = simulation
        self.simulation.top_level_models.insert(0, self)
        self.life_events = [] if life_events is None else life_events

    def _repr_html_(self):
        desc = 'Life Events:'
        desc += '<ul>'
        desc += ''.join(f"<li>{x.year}: {x.name}</li>" for x in self.life_events)
        desc += '</ul>'
        return desc

    def advance_year(self, objects=None):
        # Perform life events for the current year (if any)
        self.life_events = [x for x in self.life_events if not x.eval_event(self.year)]
        super().advance_year(objects)


class LifeEvent():
    def __init__(self, year, name, event, *event_args):
        """Life Event.

        Args:
            year (int): Year in which the life event takes place.
            name (str): Name of the event.
            event (Callable): Callable performed at the specified year.
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
