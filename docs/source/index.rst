

Getting Started
===============

We suggest using environments to install this package, and in particular using
[`mamba`](https://mamba.readthedocs.io/en/latest/) for the fastest installation
experience (though `conda` and `pip install` work fine too).

mamba/conda
-----------

.. code-block:: bash
    $ mamba env create -f environment.yml

*OR* pip
--------

.. code-block:: bash
    $ pip install -e .[lint,rescue,test]

You can then check to make sure your install is operating as expected

.. code-block:: bash

    pytest tests

Why aren't there notebook files?
--------------------------------

In order to be able to properly track versions and changes, all notebooks here
are in the form of python files, which can be synced as jupyter notebooks with
the [jupytext](https://jupytext.readthedocs.io/en/latest/paired-notebooks.html)
tool, e.g.,

.. code-block:: bash

    jupytext --sync workflow.py # generates a workflow.ipynb file

If you make a material change to `workflow.ipynb`, you can resync it manually if
needed with

.. code-block:: bash

    jupytext --sync workflow.ipynb # updates the workflow.py file

Anatomy of a Workflow
=====================

The purpose of a workflow is to support the harmonization of IAM emission data
to a compiled historical data set, downscaling of that data, and gridding of
that data. An example of such a workflow is provided in
[`notebooks/workflow`](https://github.com/IAMconsortium/concordia/blob/main/notebooks/workflow.py)

Concepts
--------

TODO: describe harm, downscale, grid and different combinations of regional resolution

Configuration
-------------

All workflows require a configuration file, and an example is provided in
[`notebooks/example_config.yaml`](https://github.com/IAMconsortium/concordia/blob/main/notebooks/example_config.yaml).

Defining Variables
------------------

TODO: describe variabledefs

Data Requirements
-----------------

TODO: describe historical and model data and proxies

Harmonization
-------------

TODO: describe briefly harmonization concepts and point to aneris docs

Downscaling
-----------

TODO: describe briefly downscaling concepts and point to aneris docs (need to
write aneris docs on downscaling methods)

Gridding
--------

TODO: Describe dask client, proxy data, etc.

Postprocessing
--------------

TODO: describe f-gas approach

Uploading Data
--------------

TODO: describe FTP updates

Analyzing Results
=================

The most important part of a workflow related to matching the original provided
scenario data is harmonization. As a result, we provide a specific utility -
[`build-harmonization-report`](https://github.com/IAMconsortium/concordia/blob/main/notebooks/build-harmonization-report.py)
which constructs graphs for every processed trajectory. The resulting output can
be generated as a static `html` file which can be served and reviewed.





Key Downstream Depedencies
==========================

`concordia` has a number of primary downstream depedencies which serve different
purposes.

For working with large-scale gridded data computations, we take advantage the
`xarray` ecosystem, including `dask` and `flox`.

For special operations translating between vector data and grids, we use
[`ptolemy`](https://github.com/gidden/ptolemy), including its `IndexRaster`
implementation.

`concordia` operationalizes three main processes: harmonization of IAM emission
data, downscaling of that data, and gridding of that data. `concordia` tries to
stay lean in terms of just connecting the pieces together, but all
implementaiton for these different processes lives in
[`aneris`](https://github.com/iiasa/aneris).
