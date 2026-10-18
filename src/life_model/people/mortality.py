# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import random

from .types import GenderAtBirth

# Actuarial mortality table for the US population
# https://www.ssa.gov/oact/STATS/table4c6.html
#
# vintage: 2023, source: SSA period life table for the Social Security area population as used in
# the 2026 Trustees Report (https://www.ssa.gov/oact/STATS/table4c6.html, "Period Life Table, 2023").
# Identified by its published values (age-0 death probabilities 0.006015 male / 0.005125 female;
# period life expectancy at birth 75.79 / 81.06). ssa.gov refuses automated clients, so the values
# were read from the Internet Archive capture of 2026-10-10 and checked against the page's own
# columns (the lives column chains from the death probabilities and recomputes both life expectancies).
# Age 119 is set to 1.0 to close the table (SSA publishes 0.926604 there with no lives remaining);
# ages past 119 use the age-119 rate, so the closure guarantees nobody outlives the table.
# This is a static period table with no mortality-improvement projection applied — future mortality
# is modeled at present-day rates, which is slightly pessimistic at older ages.

# Probabilities of death for each age from 0 to 119
# [Age, Male Probability, Female % Probability]
mortality_rates = [
    [0, 0.006015, 0.005125],
    [1, 0.000479, 0.000392],
    [2, 0.000320, 0.000229],
    [3, 0.000249, 0.000188],
    [4, 0.000194, 0.000155],
    [5, 0.000159, 0.000133],
    [6, 0.000137, 0.000115],
    [7, 0.000125, 0.000105],
    [8, 0.000120, 0.000100],
    [9, 0.000120, 0.000098],
    [10, 0.000125, 0.000101],
    [11, 0.000140, 0.000111],
    [12, 0.000173, 0.000126],
    [13, 0.000233, 0.000152],
    [14, 0.000327, 0.000188],
    [15, 0.000463, 0.000229],
    [16, 0.000634, 0.000273],
    [17, 0.000819, 0.000323],
    [18, 0.000999, 0.000372],
    [19, 0.001138, 0.000410],
    [20, 0.001235, 0.000441],
    [21, 0.001315, 0.000476],
    [22, 0.001378, 0.000513],
    [23, 0.001439, 0.000546],
    [24, 0.001509, 0.000582],
    [25, 0.001595, 0.000609],
    [26, 0.001685, 0.000641],
    [27, 0.001783, 0.000683],
    [28, 0.001876, 0.000740],
    [29, 0.001970, 0.000808],
    [30, 0.002085, 0.000878],
    [31, 0.002202, 0.000947],
    [32, 0.002308, 0.001018],
    [33, 0.002407, 0.001089],
    [34, 0.002490, 0.001154],
    [35, 0.002577, 0.001209],
    [36, 0.002665, 0.001263],
    [37, 0.002764, 0.001347],
    [38, 0.002864, 0.001438],
    [39, 0.002987, 0.001533],
    [40, 0.003115, 0.001643],
    [41, 0.003253, 0.001742],
    [42, 0.003419, 0.001845],
    [43, 0.003600, 0.001954],
    [44, 0.003777, 0.002075],
    [45, 0.003931, 0.002187],
    [46, 0.004073, 0.002306],
    [47, 0.004245, 0.002438],
    [48, 0.004477, 0.002595],
    [49, 0.004795, 0.002791],
    [50, 0.005126, 0.003030],
    [51, 0.005496, 0.003288],
    [52, 0.005917, 0.003554],
    [53, 0.006404, 0.003847],
    [54, 0.006923, 0.004172],
    [55, 0.007491, 0.004532],
    [56, 0.008173, 0.004923],
    [57, 0.008938, 0.005365],
    [58, 0.009714, 0.005815],
    [59, 0.010494, 0.006333],
    [60, 0.011337, 0.006923],
    [61, 0.012232, 0.007555],
    [62, 0.013196, 0.008220],
    [63, 0.014229, 0.008881],
    [64, 0.015316, 0.009514],
    [65, 0.016455, 0.010188],
    [66, 0.017574, 0.010880],
    [67, 0.018735, 0.011659],
    [68, 0.019981, 0.012543],
    [69, 0.021366, 0.013581],
    [70, 0.022903, 0.014769],
    [71, 0.024615, 0.016153],
    [72, 0.026504, 0.017705],
    [73, 0.028648, 0.019495],
    [74, 0.031071, 0.021533],
    [75, 0.033802, 0.023846],
    [76, 0.037010, 0.026458],
    [77, 0.041158, 0.029700],
    [78, 0.045461, 0.033135],
    [79, 0.050346, 0.036982],
    [80, 0.055633, 0.041183],
    [81, 0.061757, 0.045959],
    [82, 0.068358, 0.051282],
    [83, 0.075420, 0.057262],
    [84, 0.083364, 0.064107],
    [85, 0.092680, 0.071752],
    [86, 0.103459, 0.080490],
    [87, 0.115502, 0.090566],
    [88, 0.129018, 0.102204],
    [89, 0.143810, 0.115178],
    [90, 0.159458, 0.129176],
    [91, 0.176551, 0.144229],
    [92, 0.195360, 0.160353],
    [93, 0.216286, 0.177635],
    [94, 0.238799, 0.196502],
    [95, 0.262268, 0.216846],
    [96, 0.286291, 0.238750],
    [97, 0.310944, 0.261359],
    [98, 0.332325, 0.283899],
    [99, 0.349036, 0.306491],
    [100, 0.366568, 0.329680],
    [101, 0.384960, 0.353333],
    [102, 0.404252, 0.377300],
    [103, 0.424488, 0.401416],
    [104, 0.445712, 0.425501],
    [105, 0.467998, 0.451031],
    [106, 0.491398, 0.478092],
    [107, 0.515968, 0.506778],
    [108, 0.541766, 0.537185],
    [109, 0.568854, 0.568854],
    [110, 0.597297, 0.597297],
    [111, 0.627162, 0.627162],
    [112, 0.658520, 0.658520],
    [113, 0.691446, 0.691446],
    [114, 0.726018, 0.726018],
    [115, 0.762319, 0.762319],
    [116, 0.800435, 0.800435],
    [117, 0.840457, 0.840457],
    [118, 0.882480, 0.882480],
    [119, 1.000000, 1.000000],
]


def get_chance_of_mortality(age: int, gender: GenderAtBirth) -> float:
    """Get the chance of mortality for a given age and gender"""
    # Bound age to valid range
    age = 0 if age < 0 else min(age, 119)
    # Map gender to the correct index in the mortality_rates array
    gender_idx = 1 if gender == GenderAtBirth.MALE else 2
    # Find the mortality rate for the given age and gender
    entry = next((x for x in mortality_rates if x[0] == age), mortality_rates[-1])
    return entry[gender_idx]


def get_blended_chance_of_mortality(age: int) -> float:
    """Chance of mortality averaged across the male and female tables.

    Used when a person's gender is unspecified (or ``OTHER``) so mortality does not silently
    default to a single table.
    """
    return (get_chance_of_mortality(age, GenderAtBirth.MALE) + get_chance_of_mortality(age, GenderAtBirth.FEMALE)) / 2


def get_random_mortality(age: int, gender: GenderAtBirth, rng=None) -> bool:
    """Get a random chance of mortality for a given age and gender.

    Args:
        age: Person's age.
        gender: Person's gender at birth.
        rng: Random source with a ``random()`` method (e.g. ``mesa.Model.random``). When provided,
            draws are reproducible under a seeded model. Falls back to the module-level ``random``
            when omitted.
    """
    draw = rng.random() if rng is not None else random.random()
    return draw <= get_chance_of_mortality(age, gender)
