# -*- coding: utf-8 -*-
#
# This file were created by Python Boilerplate. Use boilerplate to start simple
# usable and best-practices compliant Python projects.
#
# Learn more about it at: http://github.com/fabiommendes/python-boilerplate/
#

import os
import codecs
from setuptools import setup, find_packages

# Save version and author to __meta__.py
author = 'Spencer Williams'
version = open('VERSION').read().strip()
dirname = os.path.dirname(__file__)
path = os.path.join(dirname, 'src', 'life_model', '__meta__.py')
meta = f'''# Automatically created. Please do not edit.
__version__ = '{version}'
__author__ = '{author}'
'''
with open(path, 'w') as meta_file:
    meta_file.write(meta)

setup(
    # Basic info
    name='life-model',
    version=version,
    author=author,
    author_email='sw23@users.noreply.github.com',
    url='https://github.com/sw23/life-model',
    description='Modeling life events and how they impact finances',
    long_description=codecs.open('README.rst', 'rb', 'utf8').read(),
    long_description_content_type='text/x-rst',

    # Classifiers (see https://pypi.python.org/pypi?%3Aaction=list_classifiers)
    classifiers=[
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
    ],

    # Packages and dependencies
    package_dir={'': 'src'},
    packages=find_packages('src', exclude=['life_model.tests']),
    install_requires=[
        'pandas',
        'matplotlib'
    ],

    # Other configurations
    zip_safe=False,
    platforms='any',
)
