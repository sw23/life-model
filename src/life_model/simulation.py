from datetime import date
from .basemodel import BaseModel, EventLog


class Simulation(BaseModel):
    def __init__(self, end_year=None, start_year=None):
        """Simulation Helper Class

        Args:
            end_year (int, optional): End date of the simulation. Defaults to None.
            start_year (int, optional): Start date of the simulation. Defaults to None.
        """
        if start_year is None:
            start_year = date.today().year
        if end_year is None:
            end_year = start_year + 50
        self.simulation = self
        self.top_level_models = []
        self.start_year = start_year
        self.end_year = end_year
        self._year = start_year
        self._event_log = EventLog(self)
        self.simulated_years = []

    def get_year(self):
        return self._year

    def get_event_log(self):
        return self._event_log

    def advance_year(self, objects=None):
        self.simulated_years.append(self._year)
        super().advance_year(objects)
        self._year += 1

    def get_year_range(self):
        return range(self.start_year, self.end_year + 1)
