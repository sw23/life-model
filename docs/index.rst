================================================================================
Welcome to life-model's documentation!
================================================================================

.. include:: warning.rst

life-model is a Python package for month-step personal-finance simulation built on
Mesa agent-based modeling. It models people, families, jobs, accounts, homes,
insurance and taxes over time. See the project `README on GitHub
<https://github.com/sw23/life-model#readme>`_ for a full feature overview.

Agents and scripts drive the model from a household spec with the ``life-model`` command line,
the ``life_model.run`` / ``validate`` / ``explain`` / ``compare`` functions, or the optional MCP
server; start with :doc:`modeling-a-household` and :doc:`cli`. Contributors and coding agents:
see `AGENTS.md <https://github.com/sw23/life-model/blob/main/AGENTS.md>`_.

.. toctree::
   :maxdepth: 2

   Installation instructions <install.rst>
   Modeling a household <modeling-a-household.md>
   Command line, Python functions and MCP <cli.md>
   Household spec <household-spec.md>
   Units and conventions <units-and-conventions.md>
   Constructor cheat sheet <constructor-cheatsheet.md>
   Outputs glossary <outputs.md>
   Checking the model: reconciliation, goldens, invariants, backtests <reconciliation.md>
   Backtest example 2020-2025 <backtest-2020-2025.md>
   Configuration <configuration.md>
   API documentation <apidoc.rst>
   License <license.rst>

.. toctree::
   :maxdepth: 1
   :caption: Agent skills

   model-household (Claude Code skill) <agent-skills/model-household/SKILL.md>

.. toctree::
   :maxdepth: 1
   :caption: Re-baseline logs

   Plan 26: engine timing and settlement <rebaseline-plan-26.md>
   Plan 28: explainable outputs <rebaseline-plan-28.md>
   Plan 29: reconciliation and calibration <rebaseline-plan-29.md>
   Plan 31: tax completeness <rebaseline-plan-31.md>
   Plan 32: monthly engine <rebaseline-plan-32.md>

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
