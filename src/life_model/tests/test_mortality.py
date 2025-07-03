# Copyright 2025 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import unittest
from unittest.mock import patch

from ..people.mortality import get_chance_of_mortality, get_random_mortality, mortality_rates
from ..people.person import GenderAtBirth


class TestMortality(unittest.TestCase):

    def test_mortality_rates_age_sequence(self):
        """Test that mortality_rates contains all ages from 0 to 119 in sequence"""
        expected_ages = list(range(120))  # 0 through 119
        actual_ages = [entry[0] for entry in mortality_rates]

        self.assertEqual(len(mortality_rates), 120, "Should have exactly 120 entries")
        self.assertEqual(actual_ages, expected_ages, "Ages should be 0 through 119 in sequence")

    def test_mortality_rates_structure(self):
        """Test that each mortality rate entry has the correct structure"""
        for i, entry in enumerate(mortality_rates):
            with self.subTest(age=i):
                self.assertEqual(len(entry), 3, f"Entry for age {i} should have 3 elements")
                self.assertEqual(entry[0], i, f"First element should be age {i}")
                self.assertIsInstance(entry[1], float, f"Male mortality rate should be float for age {i}")
                self.assertIsInstance(entry[2], float, f"Female mortality rate should be float for age {i}")
                self.assertGreaterEqual(entry[1], 0.0, f"Male mortality rate should be non-negative for age {i}")
                self.assertLessEqual(entry[1], 1.0, f"Male mortality rate should be <= 1.0 for age {i}")
                self.assertGreaterEqual(entry[2], 0.0, f"Female mortality rate should be non-negative for age {i}")
                self.assertLessEqual(entry[2], 1.0, f"Female mortality rate should be <= 1.0 for age {i}")

    def test_mortality_rates_final_age(self):
        """Test that mortality rate at age 119 is 1.0 for both genders"""
        final_entry = mortality_rates[-1]
        self.assertEqual(final_entry[0], 119, "Final entry should be for age 119")
        self.assertEqual(final_entry[1], 1.0, "Male mortality rate at 119 should be 1.0")
        self.assertEqual(final_entry[2], 1.0, "Female mortality rate at 119 should be 1.0")

    def test_get_chance_of_mortality_valid_ages(self):
        """Test get_chance_of_mortality for valid ages"""
        # Test known values from the mortality table
        self.assertEqual(get_chance_of_mortality(0, GenderAtBirth.MALE), 0.006064)
        self.assertEqual(get_chance_of_mortality(0, GenderAtBirth.FEMALE), 0.005119)
        self.assertEqual(get_chance_of_mortality(119, GenderAtBirth.MALE), 1.0)
        self.assertEqual(get_chance_of_mortality(119, GenderAtBirth.FEMALE), 1.0)

        # Test a middle age
        self.assertEqual(get_chance_of_mortality(50, GenderAtBirth.MALE), 0.005666)
        self.assertEqual(get_chance_of_mortality(50, GenderAtBirth.FEMALE), 0.003407)

    def test_get_chance_of_mortality_boundary_ages(self):
        """Test get_chance_of_mortality for boundary conditions"""
        # Test negative age (should be bounded to 0)
        self.assertEqual(get_chance_of_mortality(-1, GenderAtBirth.MALE),
                         get_chance_of_mortality(0, GenderAtBirth.MALE))
        self.assertEqual(get_chance_of_mortality(-10, GenderAtBirth.FEMALE),
                         get_chance_of_mortality(0, GenderAtBirth.FEMALE))

        # Test age above 119 (should be bounded to 119)
        self.assertEqual(get_chance_of_mortality(120, GenderAtBirth.MALE), 1.0)
        self.assertEqual(get_chance_of_mortality(150, GenderAtBirth.FEMALE), 1.0)

    def test_get_chance_of_mortality_other_gender(self):
        """Test get_chance_of_mortality with OTHER gender (should use female rates)"""
        # OTHER gender should use female mortality rates (index 2)
        for age in [0, 25, 50, 75, 119]:
            female_rate = get_chance_of_mortality(age, GenderAtBirth.FEMALE)
            other_rate = get_chance_of_mortality(age, GenderAtBirth.OTHER)

            self.assertEqual(other_rate, female_rate, f"OTHER gender should use female rate at age {age}")

    def test_get_random_mortality_deterministic(self):
        """Test get_random_mortality with mocked random values"""
        # Test with random value below mortality rate (should return True - death)
        with patch('random.random', return_value=0.001):
            self.assertTrue(get_random_mortality(50, GenderAtBirth.MALE))
            self.assertTrue(get_random_mortality(50, GenderAtBirth.FEMALE))

        # Test with random value above mortality rate (should return False - survival)
        with patch('random.random', return_value=0.9):
            self.assertFalse(get_random_mortality(0, GenderAtBirth.MALE))
            self.assertFalse(get_random_mortality(0, GenderAtBirth.FEMALE))

    def test_get_random_mortality_edge_cases(self):
        """Test get_random_mortality edge cases"""
        # Test with random value exactly equal to mortality rate
        mortality_rate = get_chance_of_mortality(25, GenderAtBirth.MALE)
        with patch('random.random', return_value=mortality_rate):
            self.assertTrue(get_random_mortality(25, GenderAtBirth.MALE))

        # Test age 119 (mortality rate = 1.0, should always return True)
        with patch('random.random', return_value=0.999):
            self.assertTrue(get_random_mortality(119, GenderAtBirth.MALE))
            self.assertTrue(get_random_mortality(119, GenderAtBirth.FEMALE))

    def test_get_random_mortality_returns_boolean(self):
        """Test that get_random_mortality always returns a boolean"""
        for age in [0, 25, 50, 75, 119]:
            for gender in [GenderAtBirth.MALE, GenderAtBirth.FEMALE, GenderAtBirth.OTHER]:
                result = get_random_mortality(age, gender)
                self.assertIsInstance(result, bool, f"Result should be boolean for age {age}, gender {gender}")


if __name__ == '__main__':
    unittest.main()
