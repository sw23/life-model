
def job_401k_contrib_limit(age):
    return 20500 + (0 if (age < 50) else 6500)


def federal_retirement_age():
    return 59.5


def required_min_distrib(age):
    return 0 * age  # TODO
