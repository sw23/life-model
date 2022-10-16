from math import e as const_e


def compound_interest(principal, rate, num_times_applied=1, elapsed_time_periods=1):
    return principal * pow(1 + ((rate / 100) / num_times_applied), num_times_applied * elapsed_time_periods) - principal


def continous_interest(principal, rate, elapsed_time_periods=1):
    return principal * pow(const_e, (rate / 100) * elapsed_time_periods) - principal


FMT_MONEY = '${:,.0f}'


class Stat:
    def __init__(self, name, title=None, fmt=None, aggregator=None):
        """Stat

        Args:
            name (str): Name of stat.
            title (str): Title of stat.
            fmt (str, Optional): Format string for printing.
        """
        self.name = name
        self.title = title or name
        self.fmt = fmt
        self.aggregator = aggregator or sum


class MoneyStat(Stat):
    def __init__(self, name, title=None):
        super().__init__(name, title, FMT_MONEY)


class Event:
    def __init__(self, message):
        """Event

        Args:
            message (str): Event description.
        """
        self.message = message
        self.year = 0

    def _repr_html_(self):
        return f"<tr><td>{self.year}</td><td>{self.message}</td></tr>\n"


class EventLog:
    def __init__(self, simulation):
        """Event Log

        Args:
            simulation (Simulation): Simulation.
        """
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
        MoneyStat('stat_gross_income',         'Income'),           # Gross income made in a year
        MoneyStat('stat_bank_balance',         'Bank Balance'),     # Bank account balance at the end of each year
        MoneyStat('stat_401k_balance',         '401k Balance'),     # Total 401k balance at the end of each year
        MoneyStat('stat_useable_balance',      'Useable Balance'),  # Balance available for use in a year
        MoneyStat('stat_debt',                 'Debt'),             # Total debt balance in each year
        MoneyStat('stat_taxes_paid',           'Taxes'),            # Taxes paid in a year
        MoneyStat('stat_money_spent',          'Spending'),         # Money spent in a year
        MoneyStat('stat_retirement_contrib',   '401k Contrib'),     # Money contributed to retirement in a given year
        MoneyStat('stat_retirement_match',     '401k Match'),       # Money matched by company in 401k in a given year
        MoneyStat('stat_required_min_distrib', 'RMDs'),             # Money taken out from required minimum distrib.
        MoneyStat('stat_home_expenses_paid',   'Home Expenses'),    # Money paid towards mortgage
        MoneyStat('stat_interest_paid',        'Interest Paid'),    # Money paid in interest for loans
        MoneyStat('stat_rent_paid',            'Rent Paid')         # Money paid in rent
    ]

    @property
    def year(self):
        return self.simulation.get_year()

    @property
    def event_log(self):
        return self.simulation.get_event_log()

    @classmethod
    def get_stat_by_name(cls, stat_name):
        for stat in cls.COMMON_STATS:
            if stat.name == stat_name:
                return stat
        return None

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
            stats = {x.name: 0 for x in self.COMMON_STATS}
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
