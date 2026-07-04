# Life Model Financial Simulation Dashboard

This dashboard provides an interactive interface for running financial simulations using the Mesa framework and Solara visualization. It is based on the `ExampleSimulation.ipynb` notebook and allows users to model the personal finances of a family over time.

## Features

- **Interactive Parameter Controls**: Configure family members, ages, salaries, bonuses, retirement ages, spending, 401k plans, and an optional mortgaged home
- **Economic Scenarios**: Apply a predefined economic scenario (e.g. `high_tax`, `recession`, `boom`) that adjusts taxes, inflation, and market returns
- **Real-time Simulation**: Run financial simulations and see results update immediately; playback automatically stops at the configured end year
- **Multiple Visualizations** (matplotlib charts rendered via Mesa's `make_plot_component`):
  - Financial Overview: income, bank balance, 401k balance, debt, and spending over time
  - Bank Balance Tracking: liquid assets over time
  - Retirement Savings: 401k balance, contributions, and employer match
  - Tax and Income Analysis: income vs. taxes
- **Results Tab**: view the full yearly-stats table and download it as CSV

## Installation

Install the life_model package and dashboard dependencies:

```bash
pip install -e . -r dashboard/requirements-dash.txt
```

## Running the Dashboard

```bash
solara run dashboard/app.py
```

Then open your browser to http://localhost:8765

## Dashboard Parameters

### Model Configuration
- **Economic Scenario**: choose `(default)` for the packaged defaults or one of the predefined scenarios
- **Start Year** / **End Year**: inclusive simulation range
- **Annual Salary Increase (%)** / **Annual Spending Increase (%)**: yearly growth rates
- **Bank Interest Rate (%)**: interest applied to bank balances

### Family Members (John and Jane)
- **Include John/Jane**: toggle to enable/disable each person
- **Age** / **Retirement Age**
- **Salary ($)** / **Annual Bonus (%)**
- **Annual Spending ($)**
- **Initial Bank Balance ($)**
- **Has a 401k**: toggle the retirement account
- **401k Balance ($)** / **401k Contribution (%)** / **401k Company Match (%)**

### Home (optional)
- **Include a Home**: adds a mortgaged home owned by the first enabled person (20% down payment assumed)
- **Home Price ($)** / **Mortgage Rate (%)** / **Mortgage Term (years)**

## How It Works

1. **Model Creation**: `DashboardLifeModel` (a `LifeModel` subclass) is built from the parameter controls.
2. **Family Setup**: `_add_person` creates each enabled person with a bank account, job, and optional 401k; `_add_home` optionally attaches a mortgaged home. All person defaults live in a single `PERSON_DEFAULTS` dict that also powers the control specs.
3. **Simulation**: the model runs year by year; the DataCollector records yearly stats.
4. **Visualization**: results are shown in interactive matplotlib charts and a results table.

## Data Export

Open the **Results** tab to view the yearly-stats DataFrame and click **Download results as CSV** to export it. The CSV matches `model.datacollector.get_model_vars_dataframe()`.

## Example Use Cases

1. **Retirement Planning**: adjust retirement ages and 401k contributions and see the effect on savings
2. **Scenario Analysis**: compare `high_tax` vs `low_tax`, or `recession` vs `boom`
3. **Housing Impact**: enable a home and compare outcomes with and without a mortgage
4. **Family Planning**: compare single vs. dual-income scenarios

## Technical Details

The dashboard is built using:
- **Mesa**: agent-based modeling framework for the financial simulation
- **Solara**: reactive web framework for the dashboard interface
- **life_model**: the financial simulation package

Each family member is modeled as an agent with income from a job, spending patterns, a bank account with interest, tax obligations, and optional retirement savings (401k).

## Files

- `app.py`: dashboard implementation (`DashboardLifeModel`, parameter specs, components, and the `SolaraViz` page)
- `tests/test_dashboard.py`: tests that verify the dashboard model and parameter handling
- `tests/conftest.py`: puts the `dashboard/` directory on `sys.path` for the tests

## Running the Tests

```bash
pytest dashboard/tests/
```

## Customization

To add new parameters or visualizations:

1. **Add Parameters**: add an entry to `SHARED_DEFAULTS`/`PERSON_DEFAULTS` and the corresponding control to `model_params` in `app.py`.
2. **Use Them in the Model**: read the value in `_add_person`, `_add_home`, or `DashboardLifeModel.__init__`.
3. **Create Charts**: add a `make_plot_component(...)` following the existing patterns.
4. **Update the Dashboard**: add your new component to the `components` list passed to `SolaraViz`.

## Troubleshooting

**Dashboard won't start:**
- Ensure dependencies are installed: `pip install -e . -r dashboard/requirements-dash.txt`

**Charts not displaying:**
- Verify the simulation is running by pressing **Play** or **Step**
- Check the console output for errors

**Performance issues:**
- Reduce the simulation range (End Year − Start Year)

## Support

For issues or questions:
1. Run the tests: `pytest dashboard/tests/`
2. Review the console output when running the dashboard
3. Refer to the original `ExampleSimulation.ipynb` for simulation logic
