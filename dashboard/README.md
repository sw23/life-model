# Life Model Financial Simulation Dashboard

This dashboard provides an interactive interface for running financial simulations using the Mesa framework and Solara visualization. It is based on the `ExampleSimulation.ipynb` notebook and allows users to model personal finances of a family over time.

## Features

- **Interactive Parameter Controls**: Configure family members, ages, salaries, retirement ages, and spending patterns
- **Real-time Simulation**: Run financial simulations and see results immediately
- **Multiple Visualizations**:
  - Financial Overview: Income, bank balance, 401k balance, debt, and spending over time
  - Bank Balance Tracking: Monitor liquid assets over time
  - Retirement Savings: 401k balance growth and contribution tracking
  - Tax and Income Analysis: Compare income vs. various tax obligations

## Installation

Install the life_model package and dashboard dependencies:
```bash
pip install -e . -r dashboard/requirements-dash.txt
```

## Running the Dashboard

Run the following command to start the dashboard:
```bash
solara run dashboard/app.py
```

Then open your browser to http://localhost:8765

## Dashboard Parameters

### Model Configuration
- **Start Year**: Beginning year for the simulation
- **End Year**: Ending year for the simulation

### Family Members
- **Include John/Jane**: Toggle to enable/disable family members
- **Age**: Current age of each person
- **Retirement Age**: Planned retirement age
- **Annual Salary**: Current salary
- **Annual Spending**: Base spending amount
- **Initial Bank Balance**: Starting bank account balance

### Economic Factors
- **Annual Spending Increase**: Yearly increase in spending percentage
- **Annual Salary Increase**: Yearly salary growth percentage

## How It Works

1. **Model Creation**: The dashboard creates a `LifeModel` instance based on your parameters
2. **Family Setup**: Creates family members with their associated jobs, bank accounts, and spending patterns
3. **Simulation**: Runs the financial simulation year by year, tracking various metrics
4. **Visualization**: Displays results in interactive charts using Altair/Vega-Lite

## Visualization Details

### Financial Overview Chart
Shows the progression of key financial metrics over time:
- Income (blue line)
- Bank Balance (orange line) 
- 401k Balance (green line)
- Debt (red line)
- Spending (purple line)

### Bank Balance Chart
Simple bar chart showing bank account balance progression over the simulation years.

### Retirement Savings Chart
Two-part visualization:
- Area chart showing 401k balance growth over time
- Stacked bar chart showing annual contributions (personal + employer match)

### Taxes and Income Chart
Line chart comparing:
- Total income (blue line)
- Total taxes paid (red line)

## Example Use Cases

1. **Retirement Planning**: Set different retirement ages and see how it affects savings
2. **Salary Comparison**: Compare different salary scenarios and their long-term impact
3. **Spending Analysis**: Understand how spending patterns affect long-term wealth
4. **Family Planning**: Compare single vs. dual-income scenarios

## Technical Details

The dashboard is built using:
- **Mesa**: Agent-based modeling framework for the financial simulation
- **Solara**: Reactive web framework for the dashboard interface
- **life_model**: Custom financial simulation package

The simulation models each family member as an agent with:
- Income from jobs
- Spending patterns
- Bank accounts with interest
- Tax obligations
- Retirement savings (401k)

## Files

- `app.py`: Main dashboard implementation
- `test_dashboard.py`: Test script to verify dashboard functionality

## Customization

To add new parameters or visualizations:

1. **Add Parameters**: Update the `model_params` dictionary in `dashboard.py`
2. **Modify Model**: Update the `DashboardLifeModel` class to use new parameters
3. **Create Charts**: Add new plotting functions following the pattern of existing ones
4. **Update Dashboard**: Add your new chart functions to the `components` list in `create_dashboard()`

## Troubleshooting

**Dashboard won't start:**
- Ensure all dependencies are installed
- Check that life_model package is installed with `pip install -e . -r dashboard/requirements-dash.txt`

**Charts not displaying:**
- Verify the simulation is running by checking console output
- Test components individually with `python src/life_model/tests/test_dashboard.py`

**Performance issues:**
- Reduce the simulation time range (end_year - start_year)
- Simplify parameter ranges to reduce computation

## Support

For issues or questions:
1. Check the test output: `python src/life_model/tests/test_dashboard.py`
2. Review the console output when running the dashboard
3. Refer to the original `ExampleSimulation.ipynb` for simulation logic