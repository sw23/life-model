from math import e as const_e


def compound_interest(principle, rate, num_times_applied=1, elapsed_time_periods=1):
    return principle * pow(1 + ((rate / 100) / num_times_applied), num_times_applied * elapsed_time_periods) - principle


def continous_interest(principle, rate, elapsed_time_periods=1):
    return principle * pow(const_e, (rate / 100) * elapsed_time_periods) - principle


class BaseModel:
    COMMON_STATS = [
        'stat_gross_income',        # Gross income made in a year
        'stat_useable_balance',     # Balance available for use in a year
        'stat_taxes_paid',          # Taxes paid in a year
        'stat_money_spent',         # Money spent in a year
        'stat_retirement_contrib',  # Money contributed to retirement in a given year
    ]

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
