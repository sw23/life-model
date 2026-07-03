# Copyright 2022 Spencer Williams
#
# Use of this source code is governed by an MIT license:
# https://github.com/sw23/life-model/blob/main/LICENSE

import argparse
from datetime import date

from life_model import Family, Person, Spending, LifeModel, BankAccount, __version__


def get_parser():
    """
    Creates a new argument parser.
    """
    parser = argparse.ArgumentParser('life-model')
    version = '%(prog)s ' + __version__
    parser.add_argument('--version', '-v', action='version', version=version)
    parser.add_argument('--years', '-y', type=int, default=50,
                        help='Number of years to simulate (default: 50).')
    return parser


def main(args=None):
    """
    Main entry point for your project.

    Args:
        args : list
            A of arguments as if they were input in the command line. Leave it
            None to use sys.argv.
    """

    parser = get_parser()
    args = parser.parse_args(args)

    start_year = date.today().year
    model = LifeModel(start_year=start_year, end_year=start_year + args.years)
    family = Family(model)
    person = Person(family=family, name='Spencer', age=45, retirement_age=55,
                    spending=Spending(model, base=30000))
    BankAccount(owner=person, company='Bank', balance=50000)

    model.run()

    df = model.datacollector.get_model_vars_dataframe()
    print(df.to_string(index=False))


if __name__ == '__main__':
    main()
