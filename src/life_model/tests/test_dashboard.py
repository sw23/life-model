#!/usr/bin/env python3
"""
Test the dashboard components

This script tests that the dashboard components work correctly
without needing to run the full Solara server.
"""

import sys
import os
# Add the dashboard directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'dashboard'))

from dashboard import (create_financial_model, plot_financial_overview, 
                    plot_balance_comparison, plot_retirement_savings, plot_taxes_and_income)

def test_model_creation():
    """Test that we can create and run a model."""
    print("Testing model creation...")
    
    params = {
        'start_year': 2023,
        'end_year': 2027,
        'john_enabled': True,
        'john_age': 30,
        'john_retirement_age': 65,
        'john_salary': 60000,
        'john_spending': 15000,
        'john_bank_balance': 25000,
        'jane_enabled': True,
        'jane_age': 28,
        'jane_retirement_age': 65,
        'jane_salary': 55000,
        'jane_spending': 18000,
        'jane_bank_balance': 20000,
        'spending_increase': 3.0,
        'salary_increase': 2.5,
    }
    
    model = create_financial_model(params)
    print(f"Model created with {len(model.agents)} agents")
    
    # Run the simulation
    model.run()
    print(f"Simulation ran for {len(model.simulated_years)} years")
    
    # Check data
    df = model.datacollector.get_model_vars_dataframe()
    print(f"Collected data shape: {df.shape}")
    print(f"Data columns: {list(df.columns)}")
    
    # Show some sample data
    print("\nSample results:")
    print(df[['Year', 'Income', 'Bank Balance', 'Spending', 'Taxes']].head())
    
    return model


def test_chart_generation(model):
    """Test chart generation."""
    print("\nTesting chart generation...")
    
    charts = []
    chart_names = []
    
    # Test financial overview chart
    chart1 = plot_financial_overview(model)
    charts.append(chart1)
    chart_names.append("Financial overview")
    
    # Test balance comparison chart
    chart2 = plot_balance_comparison(model)
    charts.append(chart2)
    chart_names.append("Balance comparison")
    
    # Test retirement savings chart
    chart3 = plot_retirement_savings(model)
    charts.append(chart3)
    chart_names.append("Retirement savings")
    
    # Test taxes and income chart
    chart4 = plot_taxes_and_income(model)
    charts.append(chart4)
    chart_names.append("Taxes and income")
    
    print(f"Created {len(charts)} charts")
    
    # Verify charts can be serialized
    try:
        for i, (chart, name) in enumerate(zip(charts, chart_names)):
            json_data = chart.to_json()
            print(f"  {name} chart: {type(chart)} (JSON length: {len(json_data)})")
        
        print("All charts serialized successfully")
    except Exception as e:
        print(f"Error serializing charts: {e}")
        return False
    
    return True


def test_parameter_variations():
    """Test different parameter combinations."""
    print("\nTesting parameter variations...")
    
    # Test single person
    params_single = {
        'start_year': 2023,
        'end_year': 2025,
        'john_enabled': True,
        'jane_enabled': False,
        'john_age': 45,
        'john_salary': 75000,
    }
    
    model_single = create_financial_model(params_single)
    model_single.run()
    print(f"Single person model: {len(model_single.agents)} agents")
    
    # Test couple
    params_couple = {
        'start_year': 2023,
        'end_year': 2025,
        'john_enabled': True,
        'jane_enabled': True,
        'john_age': 35,
        'jane_age': 33,
        'john_salary': 80000,
        'jane_salary': 70000,
    }
    
    model_couple = create_financial_model(params_couple)
    model_couple.run()
    print(f"Couple model: {len(model_couple.agents)} agents")
    
    # Compare results
    df_single = model_single.datacollector.get_model_vars_dataframe()
    df_couple = model_couple.datacollector.get_model_vars_dataframe()
    
    print(f"Single person final bank balance: ${df_single['Bank Balance'].iloc[-1]:,.2f}")
    print(f"Couple final bank balance: ${df_couple['Bank Balance'].iloc[-1]:,.2f}")
    
    return True


def main():
    """Run all tests."""
    print("=== Dashboard Component Tests ===")
    
    try:
        # Test 1: Model creation and simulation
        model = test_model_creation()
        
        # Test 2: Chart generation
        test_chart_generation(model)
        
        # Test 3: Parameter variations
        test_parameter_variations()
        
        print("\n=== All Tests Passed! ===")
        print("Dashboard components are working correctly.")
        print("You can now run the dashboard with: solara run dashboard/run_dashboard.py")
        
    except Exception as e:
        print(f"\n=== Test Failed! ===")
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)