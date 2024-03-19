# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.16.1
#   kernelspec:
#     display_name: concordia
#     language: python
#     name: python3
# ---

# %%
# %load_ext autoreload
# %autoreload 2

# %%
import aneris


aneris.__file__

# %%
import logging
from pathlib import Path

import dask
import pandas as pd
from dask.distributed import Client
from pandas_indexing import concat, isin, ismatch, semijoin
from pandas_indexing.units import set_openscm_registry_as_default
from ptolemy.raster import IndexRaster

from aneris import logger
from concordia import (
    RegionMapping,
    VariableDefinitions,
)
from concordia.rescue import utils as rescue_utils
from concordia.settings import Settings
from concordia.utils import DaskSetWorkerLoglevel, MultiLineFormatter
from concordia.workflow import WorkflowDriver


# %%
ur = set_openscm_registry_as_default()

# %% [markdown]
# # Read model and historic data including overrides
#
# To run this code, create a file called `config.yaml` in this directory pointing to the correct data file locations, e.g.,
#
# ```
# # config.yaml
# base_path: "~/Library/CloudStorage/OneDrive-SharedLibraries-IIASA/RESCUE - WP 1/data"
# data_path: "../data"
# country_combinations:
#   sdn_ssd: ["ssd", "sdn"]
#   isr_pse: ["isr", "pse"]
#   srb_ksv: ["srb", "srb (kosovo)"]
# ```
#

# %%
settings = Settings.from_config(version="2024-03-18")

# %%
fh = logging.FileHandler(settings.out_path / f"debug_{settings.version}.log", mode="w")
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
fh.setFormatter(formatter)


streamhandler = logging.StreamHandler()
streamhandler.setFormatter(
    MultiLineFormatter(
        "%(log_color)s%(levelname)-8s%(reset)s %(message)s  (%(blue)s%(name)s%(reset)s)",
        datefmt=None,
        reset=True,
    )
)

logger().handlers = [streamhandler, fh]

# %% [markdown]
# ## Variable definition files
#
# The variable definition file is a CSV or yaml file that needs to contain the `variable`-name, its `sector`, `gas` components and whether it is expected `global` (or regional instead).
#
# Here we generate one based on the cmip6 historical data we have that could be used as a basis but we would want to finetune this by hand.
#

# %%
variabledefs = VariableDefinitions.from_csv(
    settings.data_path / "variabledefs-rescue.csv"
)
variabledefs.data.tail()

# %% [markdown]
# ## RegionMapping helps reading in a region definition file
#

# %%
regionmapping = RegionMapping.from_regiondef(
    settings.shared_path / "iam_files/rescue/regionmappingH12.csv",
    country_column="CountryCode",
    region_column="RegionCode",
    sep=";",
)
regionmapping.data = regionmapping.data.pix.aggregate(
    country=settings.country_combinations, agg_func="last"
)

# %% [markdown]
# ## Model and historic data read in
#
# Can be read in and prepared using `read_iamc` or the `variabledefs`
#

# %%
hist_ceds = (
    pd.read_csv(
        settings.shared_path / "historical/rescue/ceds_2017_extended.csv",
        index_col=list(range(4)),
    )
    .rename(index={"NMVOC": "VOC", "SO2": "Sulfur"}, level="gas")
    .rename(index={"Mt NMVOC/yr": "Mt VOC/yr"}, level="unit")
    .rename(columns=int)
    .pix.format(variable=settings.variable_template, drop=True)
    .pix.assign(model="History", scenario="CEDS")
)

# %%
hist_global = (
    pd.read_excel(
        settings.shared_path / "historical/rescue/global_trajectories.xlsx",
        index_col=list(range(5)),
    )
    .rename_axis(index=str.lower)
    .rename_axis(index={"region": "country"})
    .rename(
        index=lambda s: s.removesuffix("|Unharmonized")
        + ("|Total" if "Agriculture and LUC" not in s else ""),
        level="variable",
    )
)

# %%
hist_gfed = pd.read_csv(
    settings.shared_path / "historical/rescue/gfed/GFED2015_extended.csv",
    index_col=list(range(5)),
).rename(columns=int)

# %%
hist = (
    concat([hist_ceds, hist_global, hist_gfed])
    .droplevel(["model", "scenario"])
    .pix.aggregate(country=settings.country_combinations)
    .pipe(
        variabledefs.load_data,
        extend_missing=True,
        levels=["country", "gas", "sector", "unit"],
        settings=settings,
    )
)
hist.head()


# %%
def patch_model_variable(var):
    if var.endswith("|Energy Sector"):
        var += "|Modelled"
    return var


# %%
with ur.context("AR4GWP100"):
    model = (
        pd.read_csv(
            settings.shared_path
            / "iam_files/rescue/REMIND-MAgPIE-CEDS-RESCUE-Tier1-2023-12-13.csv",
            index_col=list(range(5)),
            sep=";",
        )
        .drop(["Unnamed: 21"], axis=1)
        .rename(
            index={
                "Mt CO2-equiv/yr": "Mt CO2eq/yr",
                "Mt NOX/yr": "Mt NOx/yr",
                "kt HFC134a-equiv/yr": "kt HFC134a/yr",
            },
            level="Unit",
        )
        .pix.convert_unit({"kt HFC134a/yr": "Mt CO2eq/yr"}, level="Unit")
        .rename(index=patch_model_variable, level="Variable")
        .pipe(
            variabledefs.load_data,
            extend_missing=True,
            levels=["model", "scenario", "region", "gas", "sector", "unit"],
            settings=settings,
        )
        # .loc[ismatch(scenario=["*-Baseline", "*-PkBudg_cp2300-OAE_off", "*-Direct-*"])]
    )
model.pix

# %%
harm_overrides = pd.read_excel(
    settings.shared_path / "iam_files" / "rescue" / "harmonization_overrides.xlsx",
    index_col=list(range(3)),
).method
harm_overrides

# %% [markdown]
# ## Prepare GDP proxy
#
# Read in different GDP scenarios for SSP1 to SSP5 from SSP DB.
#

# %%
gdp = (
    pd.read_csv(
        settings.shared_path / "historical" / "SspDb_country_data_2013-06-12.csv",
        index_col=list(range(5)),
    )
    .rename_axis(index=str.lower)
    .loc[
        isin(
            model="OECD Env-Growth",
            scenario=[f"SSP{n+1}_v9_130325" for n in range(5)],
            variable="GDP|PPP",
        )
    ]
    .dropna(how="all", axis=1)
    .rename_axis(index={"scenario": "ssp", "region": "country"})
    .rename(index=str.lower, level="country")
    .rename(columns=int)
    .pix.project(["ssp", "country"])
    .pix.aggregate(country=settings.country_combinations)
)

# %% [markdown]
# Determine likely SSP for each harmonized pathway from scenario string and create proxy data aligned with pathways
#

# %%
SSP_per_pathway = (
    model.index.pix.project(["model", "scenario"])
    .unique()
    .to_frame()
    .scenario.str.extract("(SSP[1-5])")[0]
    .fillna("SSP2")
)
gdp = semijoin(
    gdp,
    SSP_per_pathway.index.pix.assign(ssp=SSP_per_pathway + "_v9_130325"),
    how="right",
).pix.project(["model", "scenario", "country"])

# %%
# Test with one scenario only
if True:
    model = model.loc[ismatch(scenario="RESCUE-Tier1-Direct-*-PkBudg500-OAE_on")]

    # model = model.pix.semijoin(
    #     model.pix.unique(["model", "scenario"])[:2], how="right"
    # )
logger().info(
    "Running with %d scenario(s):\n- %s",
    len(model.pix.unique(["model", "scenario"])),
    "\n- ".join(model.pix.unique("scenario")),
)

# %%
client = Client()
client.register_plugin(DaskSetWorkerLoglevel(logger().getEffectiveLevel()))
client.forward_logging()

# %%
dask.distributed.utils_perf.disable_gc_diagnosis()

# %%
indexraster = IndexRaster.from_netcdf(
    settings.gridding_path / "ssp_comb_indexraster.nc",
    chunks={},
).persist()

# %%
workflow = WorkflowDriver(
    model,
    hist,
    gdp,
    regionmapping.filter(gdp.pix.unique("country")),
    indexraster,
    variabledefs,
    harm_overrides,
    settings,
)

# %%
version_path = settings.out_path / settings.version
version_path.mkdir(parents=True, exist_ok=True)

# %% [markdown]
# # Harmonize, downscale and grid everything
#
# Latest test with 2 scenarios was 70 minutes for everything on MacBook

# %% [markdown]
# ## Alternative 1) Run full processing and create netcdf files

# %%
res = workflow.grid(
    template_fn="{{name}}_{activity_id}_emissions_{target_mip}_{institution}-{{model}}-{{scenario}}-{version}_{grid_label}_201501-210012.nc".format(
        **rescue_utils.DS_ATTRS | {"version": settings.version}
    ),
    callback=rescue_utils.DressUp(version=settings.version),
    encoding_kwargs=dict(_FillValue=1e20),
    directory=version_path,
)

# %% [markdown]
# ## Alternative 2) Harmonize and downscale everything, but do not grid
#
# If you also want grids, use the gridding interface directly
#

# %%
workflow.harmonize_and_downscale()

# %% [markdown]
# ## Alternative 3) Investigations

# %% [markdown]
# ### Process single proxy
#
# `workflow.grid_proxy` returns an iterator of the gridded scenarios. We are looking at the first one in depth.

# %%
gridded = next(workflow.grid_proxy("CO2_em_anthro"))

# %%
ds = gridded.prepare_dataset(callback=rescue_utils.DressUp(version=settings.version))
ds

# %%
ds.isnull().any(["time", "lat", "lon"])["CO2_em_anthro"].to_pandas()

# %%
reldiff, _ = dask.compute(
    gridded.verify(compute=False),
    gridded.to_netcdf(
        template_fn=(
            "{{name}}_{activity_id}_emissions_{target_mip}_{institution}-"
            "{{model}}-{{scenario}}-{version}_{grid_label}_201501-210012.nc"
        ).format(**rescue_utils.DS_ATTRS | {"version": settings.version}),
        callback=rescue_utils.DressUp(version=settings.version),
        encoding_kwargs=dict(_FillValue=1e20),
        compute=False,
        directory=version_path,
    ),
)
reldiff

# %% [markdown]
# ### Regional proxy weights

# %%
gridded.proxy.weight.regional.sel(
    sector="Transportation Sector", year=2050, gas="CO2"
).compute().to_pandas().plot.hist(bins=100, logx=True, logy=True)

# %% [markdown]
# ## Export harmonized scenarios
#

# %%
data = workflow.harmonized_data.add_totals().to_iamc(
    settings.variable_template, hist_scenario="Synthetic (GFED/CEDS/Global)"
)
data.to_csv(version_path / f"harmonization-{settings.version}.csv")

# %% [markdown]
# ### Split HFC distributions
#

# %%
hfc_distribution = (
    pd.read_excel(
        settings.shared_path
        / "harmonization_postprocessing"
        / "rescue"
        / "rescue_hfc_scenario.xlsx",
        index_col=0,
        sheet_name="velders_2015",
    )
    .rename_axis("hfc")
    .rename(columns=int)
)

data = (
    workflow.harmonized_data.drop_method()
    .add_totals()
    .aggregate_subsectors()
    .split_hfc(hfc_distribution)
    .to_iamc(settings.variable_template, hist_scenario="Synthetic (GFED/CEDS/Global)")
)
data.to_csv(version_path / f"harmonization-{settings.version}-splithfc.csv")

# %% [markdown]
# # Export downscaled results
#
# TODO: create a similar exporter to the Harmonized class for Downscaled which combines historic and downscaled data (maybe also harmonized?) and translates to iamc
#

# %%
# Do we also want to render this as IAMC?
workflow.downscaled.data.to_csv(
    version_path / f"downscaled-only-{settings.version}.csv"
)

# %% [markdown]
# # Upload to BSC FTP
#

# %%
remote_path = Path("/forcings/emissions") / settings.version
rescue_utils.ftp_upload(settings.ftp, version_path, remote_path)
