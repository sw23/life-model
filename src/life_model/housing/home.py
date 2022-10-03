from ..basemodel import BaseModel


class Home(BaseModel):
    def __init__(self, person, name, purchase_price, value_yearly_increase,
                 down_payment, mortgage, expenses):
        self.simulation = person.simulation
        self.name = name
        self.purchase_price = purchase_price
        self.value_yearly_increase = value_yearly_increase
        self.down_payment = down_payment
        self.mortgage = mortgage
        self.expenses = expenses
        self.expenses.home = self
        self.home_value = self.purchase_price
        person.homes.append(self)

    @property
    def yearly_expenses_due(self):
        return self.expenses.get_yearly_spending() + self.mortgage.get_payment_due_for_year()

    def make_yearly_payment(self, yearly_payment=None, extra_to_principal=0):
        if yearly_payment is None:
            yearly_payment = self.yearly_expenses_due
        base_mortgage_payment = yearly_payment - self.expenses.get_yearly_spending()
        self.mortgage.make_yearly_payment(base_mortgage_payment, extra_to_principal)
        return yearly_payment + extra_to_principal

    def _repr_html_(self):
        return f"{self.name}, purchase price ${self.purchase_price:,}, " \
               + f"monthly mortgage ${self.mortgage.monthly_payment:,}"

    def advance_year(self, objects=None):
        super().advance_year(objects)
        self.home_value += self.home_value * (self.value_yearly_increase / 100)


class HomeExpenses(BaseModel):
    def __init__(self, property_tax_percent, home_insurance_percent,
                 maintenance_amount, maintenance_increase,
                 improvement_amount, improvement_increase,
                 hoa_amount, hoa_increase):
        self.property_tax_percent = property_tax_percent
        self.home_insurance_percent = home_insurance_percent
        self.maintenance_amount = maintenance_amount
        self.maintenance_increase = maintenance_increase
        self.improvement_amount = improvement_amount
        self.improvement_increase = improvement_increase
        self.hoa_amount = hoa_amount
        self.hoa_increase = hoa_increase
        self.home = None

    def get_yearly_spending(self):
        spending_amount = self.home.home_value * (self.property_tax_percent / 100)
        spending_amount += self.home.home_value * (self.home_insurance_percent / 100)
        spending_amount += self.maintenance_amount + self.improvement_amount + self.hoa_amount
        return spending_amount

    def advance_year(self, objects=None):
        super().advance_year(objects)
        self.maintenance_amount += self.maintenance_amount * (self.maintenance_increase / 100)
        self.improvement_amount += self.improvement_amount * (self.improvement_increase / 100)
        self.hoa_amount += self.hoa_amount * (self.hoa_increase / 100)


# https://www.nerdwallet.com/mortgages/mortgage-calculator/calculate-mortgage-payment
# https://www.valuepenguin.com/mortgages/mortgage-payments-calculator
# https://www.investopedia.com/calculate-principal-and-interest-5211981
class Mortgage:
    def __init__(self, loan_amount, start_date, length_years, yearly_interest_rate,
                 principal=None, monthly_payment=None):
        # TODO - Need to add PMI
        self.loan_amount = loan_amount
        self.start_date = start_date
        self.length_years = length_years
        self.yearly_interest_rate = yearly_interest_rate
        self.principal = principal or loan_amount
        self.monthly_payment = monthly_payment or self.get_monthly_payment()
        self.yearly_payment = self.monthly_payment * 12

        self.stat_principal_payment_history = []
        self.stat_interest_payment_history = []
        self.stat_principal_balance_history = []

    def get_monthly_payment(self):
        p = self.loan_amount
        i = self.yearly_interest_rate / (100 * 12)
        n = self.length_years * 12
        return p * (i * ((1 + i) ** n)) / (((1 + i) ** n) - 1)

    def get_payment_due_for_year(self):
        return min(self.yearly_payment,
                   self.principal + (self.principal * (self.yearly_interest_rate / 100)))

    def get_interest_for_year(self):
        return self.principal * (self.yearly_interest_rate / 100)

    def make_yearly_payment(self, yearly_payment, extra_to_principal=0):
        interest_amount = self.get_interest_for_year()
        principal_amount = (yearly_payment - interest_amount) + extra_to_principal
        self.principal -= principal_amount

        self.stat_principal_payment_history.append(principal_amount)
        self.stat_interest_payment_history.append(interest_amount)
        self.stat_principal_balance_history.append(self.principal)
