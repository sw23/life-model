#!/usr/bin/env python3
"""
Demo script showing the Life Model Financial Simulation Dashboard

This script demonstrates the key features of the dashboard by running
several example scenarios and displaying the results.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from dashboard import create_financial_model
import json

def demo_single_professional():
    """Demo scenario: Single professional planning for retirement."""
    print("=" * 60)
    print("DEMO 1: Single Professional - Early Career")
    print("=" * 60)
    
    params = {
        'start_year': 2024,
        'end_year': 2040,
        'john_enabled': True,
        'john_age': 25,
        'john_retirement_age': 65,
        'john_salary': 75000,
        'john_spending': 20000,
        'john_bank_balance': 10000,
        'jane_enabled': False,
        'spending_increase': 3.0,
        'salary_increase': 3.5,
    }
    
    model = create_financial_model(params)
    model.run()
    
    df = model.datacollector.get_model_vars_dataframe()
    
    print(f"Simulation Summary:")
    print(f"  Starting salary: ${params['john_salary']:,}")
    print(f"  Starting bank balance: ${params['john_bank_balance']:,}")
    print(f"  Years simulated: {len(df)} years")
    print(f"  Final bank balance: ${df['Bank Balance'].iloc[-1]:,.2f}")
    print(f"  Final income: ${df['Income'].iloc[-1]:,.2f}")
    print(f"  Total taxes paid: ${df['Taxes'].sum():,.2f}")
    print(f"  Total spending: ${df['Spending'].sum():,.2f}")
    
    return model

def demo_family_scenario():
    """Demo scenario: Young family planning together."""
    print("\n" + "=" * 60)
    print("DEMO 2: Young Family - Dual Income")
    print("=" * 60)
    
    params = {
        'start_year': 2024,
        'end_year': 2045,
        'john_enabled': True,
        'john_age': 32,
        'john_retirement_age': 62,
        'john_salary': 85000,
        'john_spending': 18000,
        'john_bank_balance': 25000,
        'jane_enabled': True,
        'jane_age': 30,
        'jane_retirement_age': 62,
        'jane_salary': 70000,
        'jane_spending': 22000,
        'jane_bank_balance': 15000,
        'spending_increase': 2.5,
        'salary_increase': 2.8,
    }
    
    model = create_financial_model(params)
    model.run()
    
    df = model.datacollector.get_model_vars_dataframe()
    
    print(f"Simulation Summary:")
    print(f"  Combined starting salary: ${params['john_salary'] + params['jane_salary']:,}")
    print(f"  Combined starting balance: ${params['john_bank_balance'] + params['jane_bank_balance']:,}")
    print(f"  Years simulated: {len(df)} years")
    print(f"  Final bank balance: ${df['Bank Balance'].iloc[-1]:,.2f}")
    print(f"  Final income: ${df['Income'].iloc[-1]:,.2f}")
    print(f"  Final spending: ${df['Spending'].iloc[-1]:,.2f}")
    print(f"  Net worth growth: ${df['Bank Balance'].iloc[-1] - (params['john_bank_balance'] + params['jane_bank_balance']):,.2f}")
    
    return model

def demo_retirement_planning():
    """Demo scenario: Mid-career retirement planning."""
    print("\n" + "=" * 60)
    print("DEMO 3: Mid-Career - Retirement Planning")
    print("=" * 60)
    
    params = {
        'start_year': 2024,
        'end_year': 2050,
        'john_enabled': True,
        'john_age': 45,
        'john_retirement_age': 60,
        'john_salary': 120000,
        'john_spending': 35000,
        'john_bank_balance': 75000,
        'jane_enabled': True,
        'jane_age': 43,
        'jane_retirement_age': 60,
        'jane_salary': 95000,
        'jane_spending': 30000,
        'jane_bank_balance': 50000,
        'spending_increase': 2.0,
        'salary_increase': 1.5,
    }
    
    model = create_financial_model(params)
    model.run()
    
    df = model.datacollector.get_model_vars_dataframe()
    
    print(f"Simulation Summary:")
    print(f"  Years to retirement: {params['john_retirement_age'] - params['john_age']}")
    print(f"  Combined peak salary: ${params['john_salary'] + params['jane_salary']:,}")
    print(f"  Starting net worth: ${params['john_bank_balance'] + params['jane_bank_balance']:,}")
    print(f"  Years simulated: {len(df)} years")
    print(f"  Final bank balance: ${df['Bank Balance'].iloc[-1]:,.2f}")
    print(f"  Retirement readiness: {'Strong' if df['Bank Balance'].iloc[-1] > 500000 else 'Moderate' if df['Bank Balance'].iloc[-1] > 200000 else 'Needs Improvement'}")
    
    # Show year-by-year progression
    print(f"\nFinancial progression (every 5 years):")
    for i, row in df.iterrows():
        if i % 5 == 0 or i == len(df) - 1:
            print(f"  {int(row['Year'])}: Bank=${row['Bank Balance']:>10,.0f}, Income=${row['Income']:>10,.0f}, Spending=${row['Spending']:>8,.0f}")
    
    return model

def main():
    """Run all demo scenarios."""
    print("Life Model Financial Simulation Dashboard - Demo Scenarios")
    print("This demonstrates the types of financial planning scenarios you can explore.")
    
    try:
        # Run demo scenarios
        model1 = demo_single_professional()
        model2 = demo_family_scenario() 
        model3 = demo_retirement_planning()
        
        print("\n" + "=" * 60)
        print("DEMO COMPLETE")
        print("=" * 60)
        print("These scenarios show different life stages and financial planning needs.")
        print("Use the interactive dashboard to explore your own scenarios!")
        print("\nTo run the interactive dashboard:")
        print("  solara run run_dashboard.py")
        print("  Then open: http://localhost:8765")
        
        print(f"\nDashboard features available:")
        print(f"  • Adjust ages, salaries, and retirement plans")
        print(f"  • Compare single vs. dual income scenarios")
        print(f"  • Visualize long-term financial projections")
        print(f"  • Track retirement savings and tax obligations")
        
    except Exception as e:
        print(f"\nDemo failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)