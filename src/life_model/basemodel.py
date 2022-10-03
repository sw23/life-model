from math import e as const_e


def compound_interest(principal, rate, num_times_applied=1, elapsed_time_periods=1):
    return principal * pow(1 + ((rate / 100) / num_times_applied), num_times_applied * elapsed_time_periods) - principal


def continous_interest(principal, rate, elapsed_time_periods=1):
    return principal * pow(const_e, (rate / 100) * elapsed_time_periods) - principal


class Event:
    def __init__(self, message):
        self.message = message
        self.year = 0

    def _repr_html_(self):
        return f"<tr><td>{self.year}</td><td>{self.message}</td></tr>\n"


class EventLog:
    def __init__(self, simulation):
        self.simulation = simulation
        self.list = []

    def _repr_html_(self):
        table = "<table>"
        table += "<tr><th>Year:</th><th>Event:</th></tr>\n"
        table += "".join(x._repr_html_() for x in self.list)
        table += "</table>"
        return table

    def add(self, event):
        event.year = self.simulation.year
        self.list.append(event)


class BaseModel:
    COMMON_STATS = [
        'stat_gross_income',          # Gross income made in a year
        'stat_bank_balance',          # Bank account balance at the end of each year
        'stat_401k_balance',          # Total 401k balance at the end of each year
        'stat_useable_balance',       # Balance available for use in a year
        'stat_debt',                  # Total debt balance in each year
        'stat_taxes_paid',            # Taxes paid in a year
        'stat_money_spent',           # Money spent in a year
        'stat_retirement_contrib',    # Money contributed to retirement in a given year
        'stat_retirement_match',      # Money matched by company in 401k in a given year
        'stat_required_min_distrib',  # Money taken out from required minimum distributions
        'stat_home_expenses_paid',    # Money paid towards mortgage
        'stat_interest_paid',         # Money paid in interest for loans
        'stat_rent_paid',             # Money paid in rent
    ]

    @property
    def year(self):
        return self.simulation.get_year()

    @property
    def event_log(self):
        return self.simulation.get_event_log()

    def advance_year(self, objects=None):
        if objects is None:
            objects = [self]
        for base_obj in (getattr(self, x) for x in vars(self)):
            obj_list = base_obj if isinstance(base_obj, list) else [base_obj]
            for obj in obj_list:
                if callable(getattr(obj, "advance_year", None)) and obj not in objects:
                    # Each object is only advanced once for a given year
                    objects.append(obj)
                    obj.advance_year(objects)

    def get_stats(self, stats=None, objects=None):
        if objects is None:
            stats = {x: 0 for x in self.COMMON_STATS}
            objects = [self]

        for stat_name in stats:
            stat_value = getattr(self, stat_name, None)
            if stat_value is not None:
                stats[stat_name] += stat_value

        for base_obj in (getattr(self, x) for x in vars(self)):
            obj_list = base_obj if isinstance(base_obj, list) else [base_obj]
            for obj in obj_list:
                if callable(getattr(obj, "get_stats", None)) and obj not in objects:
                    # Each object is only advanced once for a given year
                    objects.append(obj)
                    obj.get_stats(stats, objects)

        return stats
