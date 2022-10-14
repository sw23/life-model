# life-model (beta)
Python package for performing time step-based simulations of personal finances.  Note that this package is still early and likely contains bugs. Use at your own risk!

## Overview
The package provides models of people, jobs, accounts, etc. and provides a time step-based simulation framework. An example Jupyter Notebook is provided for quick and easy models, however the package can be used programmatically for more in-depth studies.

## Motivation
While impossible to predict the future, the goal of this package is to provide a framework for modeling financial outcomes based various inputs. The best way to use this model is to change one variable at a time and evaluate how it impacts the outcome.

## Getting Started
To get started, [check out the example simulation notebook](https://github.com/sw23/life-model/blob/main/ExampleSimulation.ipynb)

Clone this repo and open the Jupyter Notebook in a supported editor, such as [VS Code](https://code.visualstudio.com/docs/datascience/jupyter-notebooks)

To install this module locally, run the following command:
```
python -m pip install -r requirements.txt
```

## Modeling Status
This package is a work in progress. Here's what's supported currently:
- [x] Family
- [x] Adult
- [ ] Child
- [x] Job
- [x] Bank Account
- [x] 401k
- [ ] 529 Plans
- [ ] Investment Account
- [ ] Bonds
- [x] Federal Taxes
- [x] Required Minimum Distributions (RMDs)
- [ ] State Taxes
- [ ] Local Taxes
- [x] Life Events (Marriage, Retirement)
- [x] Home + Mortgage
- [x] Rent
- [ ] Life Insurance
- [ ] Annuities
- [ ] Pensions
