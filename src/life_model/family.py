from .basemodel import BaseModel


class Family(BaseModel):
    def __init__(self, *args):
        self.members = list(args)

    def __getitem__(self, key):
        matches = {x.name: x for x in self.members}
        return matches[key]

    def _repr_html_(self):
        return '<b>Family:</b><ul>' + ''.join(f"<li>{x._repr_html_()}</li>" for x in self.members) + '</ul>'

    def advance_year(self, objects=None):
        super().advance_year(objects)

        # Pay off any debts for other family members
        # TODO - Probably want to add some rules around this (e.g. parents vs. kids)
        # TODO - Currently all debts are paid off right away, but this should be modeled better
        for person_x in self.members:
            while person_x.debt > 0:
                for person_y in self.members:
                    person_x.debt = person_y.pay_bills(person_x.debt)
