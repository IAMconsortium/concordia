Workflows
=========

This folder provides workflows for generating harmonized, downscaled, and
gridded data. All notebooks here are in the form of python files, which can be
synced as jupyter notebooks with the
[jupytext](https://jupytext.readthedocs.io/en/latest/paired-notebooks.html)
tool, e.g.,

.. code-block:: bash

    jupytext --sync workflow.py # generates a workflow.ipynb file

Configuration
-------------

We use a `config.yaml` file to define a variety of configuration parameters. To
get started, copy the example file `example_config.yaml` and rename it to
`config.yaml`.

RESCUE
======

External data
-------------

External data needed is provided at [this link](TODO). It should be placed at
the location in the `config.yaml`'s  `shared_data`, which is by default
`concordia/data/rescue`.
