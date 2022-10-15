from ..basemodel import BaseModel


class Apartment(BaseModel):
    def __init__(self, person, name, monthly_rent, yearly_increase=5):
        """Apartment

        Args:
            person (Person): Primary resident or person paying apartment rent.
            name (string): Apartment Name.
            monthly_rent (float): Amount of rent charged monthly.
            yearly_increase (float, optional): Percentage of rent increase every year. Defaults to 5.
        """
        self.simulation = person.simulation
        self.name = name
        self.monthly_rent = monthly_rent
        self.yearly_increase = yearly_increase
        person.apartments.append(self)

    @property
    def yearly_rent(self):
        return self.monthly_rent * 12

    def _repr_html_(self):
        return f"{self.name}, monthly rent ${self.monthly_rent:,}"

    def advance_year(self, objects=None):
        super().advance_year(objects)

        self.monthly_rent += self.monthly_rent * (self.yearly_increase / 100)
