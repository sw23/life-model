# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

def job_401k_contrib_limit(age) -> int:
    return 20500 + (0 if (age < 50) else 6500)


def federal_retirement_age() -> float:
    return 59.5


# The table below is taken from the IRS website:
# https://www.irs.gov/pub/irs-tege/uniform_rmd_wksht.pdf
# Last accessed: 2/12/22
rmd_distribution_period = [
    # Age, Distribution Period
    [70,  27.4],
    [71,  26.5],
    [72,  25.6],
    [73,  24.7],
    [74,  23.8],
    [75,  22.9],
    [76,  22],
    [77,  21.2],
    [78,  20.3],
    [79,  19.5],
    [80,  18.7],
    [81,  17.9],
    [82,  17.1],
    [83,  16.3],
    [84,  15.5],
    [85,  14.8],
    [86,  14.1],
    [87,  13.4],
    [88,  12.7],
    [89,  12],
    [90,  11.4],
    [91,  10.8],
    [92,  10.2],
    [93,  9.6],
    [94,  9.1],
    [95,  8.6],
    [96,  8.1],
    [97,  7.6],
    [98,  7.1],
    [99,  6.7],
    [100, 6.3],
    [101, 5.9],
    [102, 5.5],
    [103, 5.2],
    [104, 4.9],
    [105, 4.5],
    [106, 4.2],
    [107, 3.9],
    [108, 3.7],
    [109, 3.4],
    [110, 3.1],
    [111, 2.9],
    [112, 2.6],
    [113, 2.4],
    [114, 2.1],
    [115, 1.9],
]


def required_min_distrib(age, balance) -> float:
    if age < rmd_distribution_period[0][0]:
        return 0
    elif age > rmd_distribution_period[-1][0]:
        return balance / rmd_distribution_period[-1][1]
    else:
        return balance / [x[1] for x in rmd_distribution_period if x[0] == age][0]
