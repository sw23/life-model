import argparse
from datetime import date
from life_model import __version__, Family, Person


def get_parser():
    """
    Creates a new argument parser.
    """
    parser = argparse.ArgumentParser('life_model')
    version = '%(prog)s ' + __version__
    parser.add_argument('--version', '-v', action='version', version=version)
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

    family = Family()
    Person(family=family, name='Spencer', age=45, retirement_age=55)

    time_data = []
    start_year = date.today().year
    years = range(start_year, start_year + 50)
    for year in years:
        family.advance_year()
        year_end_data = family.get_stats()
        year_end_data['year'] = year
        time_data.append(year_end_data)
    print(year_end_data)


if __name__ == '__main__':
    main()
