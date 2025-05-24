import unittest
from life_model.model import LifeModel, Event
from life_model.person import Person, Spending
from life_model.family import Family
from life_model.account.bank import BankAccount
from life_model.insurance.life_insurance import TermLifeInsurancePolicy, WholeLifeInsurancePolicy, LifeInsurancePolicy

class TestLifeInsurance(unittest.TestCase):
    def setUp(self):
        self.model = LifeModel(start_year=2023, end_year=2073) # Corrected: simulation_years is not a param for LifeModel
        self.family = Family(self.model, "Test Family")
        self.primary_person = Person(self.family, "Alice", 30, 65, Spending(self.model, base=20000))
        self.beneficiary_person = Person(self.family, "Bob", 28, 65, Spending(self.model, base=15000))
        
        # Give primary_person a bank account with some money
        # In the Person class, bank_accounts is a list of BankAccount objects
        # BankAccount constructor doesn't take person directly, it's added via person.bank_accounts.append
        # However, the provided BankAccount class in the broader project might have a different constructor.
        # For now, assuming BankAccount takes model and owner (Person) and adds itself to person's accounts.
        # Based on `person.py`'s `deposit_into_bank_account` it expects bank_accounts to be populated.
        # Based on `person.py`'s `deduct_from_bank_accounts` it iterates self.bank_accounts.
        # Let's assume BankAccount needs to be created and then manually added if it doesn't do it itself.
        # The provided snippet uses: BankAccount(self.model, self.primary_person, initial_balance=50000)
        # This implies BankAccount might take a person. Let's check `account/bank.py` structure if available.
        # Assuming BankAccount is as described in the prompt for now.
        # The actual BankAccount from `life_model.account.bank` is:
        # `BankAccount(self, model: LifeModel, owner: Union[Person, Family], name: str, initial_balance: float = 0)`
        # So, the setup in the prompt is mostly correct, just needs a name.

        self.primary_person_bank_account = BankAccount(self.model, self.primary_person, "Alice Checking", initial_balance=50000)
        self.primary_person.bank_accounts.append(self.primary_person_bank_account) # Ensure it's in the list

        # Give beneficiary_person a bank account
        self.beneficiary_person_bank_account = BankAccount(self.model, self.beneficiary_person, "Bob Checking", initial_balance=10000)
        self.beneficiary_person.bank_accounts.append(self.beneficiary_person_bank_account)
        
        # Add family and persons to the model's agent schedule
        # The model.agents.extend is good. BankAccount objects are also agents if they have step methods.
        # Based on `person.py`, BankAccount doesn't seem to be an agent that steps independently.
        # It's primarily managed by the Person.
        # LifeModelAgent is the base for agents that are stepped.
        # Family and Person are LifeModelAgents. BankAccount is not explicitly.
        # So, only add agents that need to be stepped by the model's scheduler.
        self.model.agents.add(self.family) # Use add for individual agents for clarity
        self.model.agents.add(self.primary_person)
        self.model.agents.add(self.beneficiary_person)
        # If BankAccount instances were agents and needed their own step, they'd be added too.
        # For now, they are primarily data holders modified by Person.

        # Set the family for the model, used by person_dies
        self.model.family = self.family


    def assert_event_logged(self, expected_message_part):
        found = False
        # Accessing event_log.list as per EventLog class structure
        for event in self.model.event_log.list:
            if expected_message_part in str(event.message): # Event class has 'message' attribute
                found = True
                break
        self.assertTrue(found, f"Event containing '{expected_message_part}' not found in log. Logged events: {[e.message for e in self.model.event_log.list]}")

    # --- Test Methods for TermLifeInsurancePolicy ---
    def test_term_life_creation_and_premium(self):
        policy = TermLifeInsurancePolicy(self.model, self.primary_person, self.beneficiary_person, 100000, 200, 10)
        self.primary_person.add_life_insurance_policy(policy)

        self.assertEqual(policy.coverage_amount, 100000)
        self.assertEqual(policy.annual_premium, 200)
        self.assertEqual(policy.term_length, 10)
        self.assertTrue(policy.is_active)
        self.assertEqual(policy.current_year_in_term, 0)

        initial_balance = self.primary_person_bank_account.balance
        
        # Simulate one year
        self.model.step() # person.step() is called by model.step()

        self.assertEqual(self.primary_person_bank_account.balance, initial_balance - policy.annual_premium)
        self.assertEqual(policy.current_year_in_term, 1)
        self.assert_event_logged(f"{self.primary_person.name} paid ${policy.annual_premium:,.2f} premium for TermLifeInsurancePolicy.")

    def test_term_life_expires(self):
        term = 2
        policy = TermLifeInsurancePolicy(self.model, self.primary_person, self.beneficiary_person, 100000, 200, term)
        self.primary_person.add_life_insurance_policy(policy)

        for _ in range(term + 1):
            self.model.step()

        self.assertFalse(policy.is_active)
        self.assert_event_logged(f"Term life insurance policy for {self.primary_person.name} has expired after {term} years.")

    def test_term_life_payout_active(self):
        policy = TermLifeInsurancePolicy(self.model, self.primary_person, self.beneficiary_person, 100000, 200, 10)
        self.primary_person.add_life_insurance_policy(policy)
        
        initial_beneficiary_balance = self.beneficiary_person_bank_account.balance
        
        # Simulate death
        self.model.person_dies(self.primary_person)

        self.assertEqual(self.beneficiary_person_bank_account.balance, initial_beneficiary_balance + policy.coverage_amount)
        self.assertFalse(policy.is_active)
        self.assert_event_logged(f"Life insurance policy for {self.primary_person.name} paid out ${policy.coverage_amount:,.2f} to {self.beneficiary_person.name}.")
        self.assert_event_logged(f"Processing payout for TermLifeInsurancePolicy of {self.primary_person.name}.")


    def test_term_life_no_payout_expired(self):
        term = 1
        policy = TermLifeInsurancePolicy(self.model, self.primary_person, self.beneficiary_person, 100000, 200, term)
        self.primary_person.add_life_insurance_policy(policy)

        # Expire the policy
        for _ in range(term + 1):
            self.model.step()
        self.assertFalse(policy.is_active)
        self.assert_event_logged("has expired") # Make sure expiry event is there

        initial_beneficiary_balance = self.beneficiary_person_bank_account.balance
        
        # Simulate death after expiry
        self.model.person_dies(self.primary_person)

        # Balance should not change due to payout
        # (Could change due to other model mechanics if we ran model.step() for beneficiary, but we are not here)
        self.assertEqual(self.beneficiary_person_bank_account.balance, initial_beneficiary_balance)
        self.assert_event_logged(f"{type(policy).__name__} for {self.primary_person.name} is inactive. No payout.")


    # --- Test Methods for WholeLifeInsurancePolicy ---
    def test_whole_life_creation_premium_cash_value(self):
        policy = WholeLifeInsurancePolicy(self.model, self.primary_person, self.beneficiary_person, 200000, 1000)
        self.primary_person.add_life_insurance_policy(policy)

        self.assertEqual(policy.coverage_amount, 200000)
        self.assertEqual(policy.annual_premium, 1000)
        self.assertTrue(policy.is_active)
        self.assertEqual(policy.cash_value, 0.0)

        initial_bank_balance = self.primary_person_bank_account.balance
        initial_cash_value = policy.cash_value

        # Simulate one year
        self.model.step() # Triggers Person.step -> policy.step -> policy.pay_premium_and_grow_cash_value

        self.assertEqual(self.primary_person_bank_account.balance, initial_bank_balance - policy.annual_premium)
        
        # Expected cash value:
        # 1. policy.step() called by Person.step():
        #    cash_value = 0 + 0 * 0.02 = 0
        # 2. policy.pay_premium_and_grow_cash_value() called by Person.step() after premium payment:
        #    cash_value_after_premium_payment_growth = 0 + 0 * 0.02 = 0
        #    cash_value_after_premium_portion = 0 + 1000 * 0.1 = 100
        # So, expected_cash_value = 100
        expected_cash_value = initial_cash_value # 0
        # Growth from policy.step()
        expected_cash_value += expected_cash_value * policy.cash_value_growth_rate
        # Growth and premium portion from pay_premium_and_grow_cash_value()
        expected_cash_value_after_first_growth = expected_cash_value
        expected_cash_value += expected_cash_value_after_first_growth * policy.cash_value_growth_rate # This is the "double growth"
        expected_cash_value += policy.annual_premium * 0.1


        self.assertAlmostEqual(policy.cash_value, expected_cash_value, places=2)
        self.assert_event_logged(f"{self.primary_person.name} paid ${policy.annual_premium:,.2f} premium for WholeLifeInsurancePolicy.")

    def test_whole_life_payout(self):
        policy = WholeLifeInsurancePolicy(self.model, self.primary_person, self.beneficiary_person, 200000, 1000)
        self.primary_person.add_life_insurance_policy(policy)
        
        initial_beneficiary_balance = self.beneficiary_person_bank_account.balance
        
        self.model.person_dies(self.primary_person)

        self.assertEqual(self.beneficiary_person_bank_account.balance, initial_beneficiary_balance + policy.coverage_amount)
        self.assertFalse(policy.is_active)
        self.assert_event_logged(f"Life insurance policy for {self.primary_person.name} paid out ${policy.coverage_amount:,.2f} to {self.beneficiary_person.name}.")

    def test_whole_life_cash_value_withdrawal(self):
        policy = WholeLifeInsurancePolicy(self.model, self.primary_person, self.beneficiary_person, 200000, 1000)
        self.primary_person.add_life_insurance_policy(policy)

        # Simulate a few years for cash value to build up
        # Year 1:
        #   step: cv = 0 + 0*0.02 = 0
        #   pay_premium_and_grow: cv = 0 + 0*0.02 = 0; cv = 0 + 1000*0.1 = 100.  So cv=100
        # Year 2:
        #   step: cv = 100 + 100*0.02 = 102
        #   pay_premium_and_grow: cv = 102 + 102*0.02 = 104.04; cv = 104.04 + 1000*0.1 = 204.04. So cv=204.04
        for _ in range(2): # Run for 2 years
            self.model.step()
        
        self.assertAlmostEqual(policy.cash_value, 204.04, places=2) # Verify buildup

        cash_value_before_withdrawal = policy.cash_value
        coverage_before_withdrawal = policy.coverage_amount
        person_bank_balance_before_withdrawal = self.primary_person_bank_account.balance
        
        withdrawal_amount = 50.0
        withdrawn = policy.withdraw_cash_value(withdrawal_amount)
        self.primary_person_bank_account.balance += withdrawn # Manually deposit to bank

        self.assertEqual(withdrawn, withdrawal_amount)
        self.assertAlmostEqual(policy.cash_value, cash_value_before_withdrawal - withdrawal_amount, places=2)
        self.assertAlmostEqual(policy.coverage_amount, coverage_before_withdrawal - withdrawal_amount, places=2)
        self.assertEqual(self.primary_person_bank_account.balance, person_bank_balance_before_withdrawal + withdrawal_amount)
        self.assert_event_logged(f"{self.primary_person.name} withdrew ${withdrawal_amount:,.2f} from whole life policy.")


    # --- Test Methods for Person Class Integration ---
    def test_person_add_policy(self):
        policy = TermLifeInsurancePolicy(self.model, self.primary_person, self.beneficiary_person, 50000, 100, 5)
        self.primary_person.add_life_insurance_policy(policy)
        self.assertIn(policy, self.primary_person.life_insurance_policies)
        self.assert_event_logged(f"{self.primary_person.name} added a {type(policy).__name__} with ${policy.coverage_amount:,.2f} coverage.")

    def test_person_premium_payment_lapse(self):
        self.primary_person_bank_account.balance = 150 # Less than premium
        
        policy = TermLifeInsurancePolicy(self.model, self.primary_person, self.beneficiary_person, 100000, 200, 10)
        self.primary_person.add_life_insurance_policy(policy)

        self.model.step() # Person pays bills

        self.assertFalse(policy.is_active)
        self.assert_event_logged(f"WARNING: {self.primary_person.name} could not afford premium of ${policy.annual_premium:,.2f} for {type(policy).__name__}. Policy now inactive.")

    def test_person_multiple_policies(self):
        term_policy = TermLifeInsurancePolicy(self.model, self.primary_person, self.beneficiary_person, 100000, 200, 10)
        whole_policy = WholeLifeInsurancePolicy(self.model, self.primary_person, self.beneficiary_person, 200000, 1000)
        
        self.primary_person.add_life_insurance_policy(term_policy)
        self.primary_person.add_life_insurance_policy(whole_policy)

        initial_bank_balance = self.primary_person_bank_account.balance
        initial_term_year = term_policy.current_year_in_term
        initial_whole_cash_value = whole_policy.cash_value

        self.model.step()

        total_premium = term_policy.annual_premium + whole_policy.annual_premium
        self.assertEqual(self.primary_person_bank_account.balance, initial_bank_balance - total_premium)
        self.assertEqual(term_policy.current_year_in_term, initial_term_year + 1)
        
        # Expected cash value for whole_policy (same logic as test_whole_life_creation_premium_cash_value)
        expected_cash_value = initial_whole_cash_value # 0
        expected_cash_value += expected_cash_value * whole_policy.cash_value_growth_rate
        expected_cash_value_after_first_growth = expected_cash_value
        expected_cash_value += expected_cash_value_after_first_growth * whole_policy.cash_value_growth_rate
        expected_cash_value += whole_policy.annual_premium * 0.1
        self.assertAlmostEqual(whole_policy.cash_value, expected_cash_value, places=2)

        self.assert_event_logged(f"{self.primary_person.name} paid ${term_policy.annual_premium:,.2f} premium for TermLifeInsurancePolicy.")
        self.assert_event_logged(f"{self.primary_person.name} paid ${whole_policy.annual_premium:,.2f} premium for WholeLifeInsurancePolicy.")

    # --- Test Methods for Payout Mechanics ---
    def test_payout_to_family_beneficiary(self):
        policy = TermLifeInsurancePolicy(self.model, self.primary_person, self.family, 150000, 300, 20)
        self.primary_person.add_life_insurance_policy(policy)

        # Family doesn't have a bank account balance to check directly in this setup.
        # We rely on the log message.
        self.model.person_dies(self.primary_person)
        
        self.assert_event_logged(f"Family {self.family.family_name} received ${policy.coverage_amount:,.2f} as beneficiary. Distribution TBD.")
        self.assertFalse(policy.is_active)


if __name__ == '__main__':
    unittest.main()
