`concordia` - Harmonization, downscaling and gridding of emissions data
=======================================================================

Getting Started
---------------

We suggest using environments to install this package, and in particular using
[`mamba`](https://mamba.readthedocs.io/en/latest/) for the fastest installation
experience (though `conda` and `pip install` work fine too).

mamba/conda
***********

.. code-block:: bash
    $ mamba env create -f environment.yml

pip
***

.. code-block:: bash
    $ pip install -e .[lint,rescue,test]

You can then check to make sure your install is operating as expected

.. code-block:: bash

    pytest tests

Running
-------
The main entrypoint is `notebooks/workflow.ipynb`. See the README file in
`notebooks`.

License
-------

Licensed under Apache 2.0. See the LICENSE file for more information
