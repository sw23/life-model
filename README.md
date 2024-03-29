# life-model (beta)
Python package for performing time step-based simulations of personal finances.  Note that this package is still early in development and likely contains bugs. Use at your own risk!

## Overview
The package provides models of people, jobs, accounts, etc. and provides a time step-based simulation framework. An example Jupyter Notebook is provided for quick and easy models, however the package can be used programmatically for more in-depth studies.

## Motivation
While impossible to predict the future, the goal of this package is to provide a framework for modeling financial outcomes based on various inputs. The best way to use this model is to change one variable at a time and evaluate how it impacts the outcome.

## Getting Started
To get started, check out the example simulation notebook:
- [Google Colab (interactive)](https://colab.research.google.com/github/sw23/life-model/blob/main/ExampleSimulation.ipynb)
- [GitHub](https://github.com/sw23/life-model/blob/main/ExampleSimulation.ipynb)

To install this module, run the following command:
```
python -m pip install life-model
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
- [ ] Debt
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
- [x] Social Security
- [x] FICA
- [ ] Charitable Giving
