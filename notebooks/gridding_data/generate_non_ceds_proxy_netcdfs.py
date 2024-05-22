# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.16.1
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %%
import geoutils as gu
import ptolemy as pt
import pyogrio as pio
import rasterio as rio
import xarray as xr
from ptolemy.raster import IndexRaster
from scipy.ndimage import gaussian_filter

from concordia.rescue.proxy import ReportMissingCountries, gu_to_xarray, plot_map
from concordia.settings import Settings


# %%
settings = Settings.from_config("config.yaml", base_path="..", version=None)

# %%
dim_order = ["gas", "sector", "level", "year", "month", "lat", "lon"]

# %%
missing_countries = ReportMissingCountries(
    IndexRaster.from_netcdf(settings.gridding_path / "ssp_comb_indexraster.nc")
)

# %% [markdown]
# # Shipping
#
# We use shipping patterns from MariTeam to generate shipping proxies. NOx, SOx,
# and CO2 are provided explicitly, and all other patterns are based on CO2, as
# NOx and SOx have specific pollution controls embedded.
#
# Citation: Kramel, D., Muri, H., Kim, Y., Lonka, R., Nielsen, J.B., Ringvold,
# A.L., Bouman, E.A., Steen, S. and Strømman, A.H., 2021. Global shipping
# emissions from a well-to-wake perspective: the MariTEAM model. Environmental
# science & technology, 55(22), pp.15040-15050.
# https://pubs.acs.org/doi/10.1021/acs.est.1c03937
#


# %%
def mariteam_shipping():
    gases = ["BC", "CH4", "CO", "CO2", "NH3", "NOx", "OC", "Sulfur", "VOC"]
    mari = {
        f.stem.split("_")[-2]: f
        for f in settings.gridding_path.glob("non_ceds_input/*MariTeam*.nc")
    }
    ceds_to_mari = {"Sulfur": "SO2"}  # maritime uses so2, ceds uses sulfur
    fallback = "CO2"  # if maritime doesn't provide data, use co2 as backup

    def convert_mariteam_to_ceds(mari, gas):
        # get path of file to use for this gas
        if gas in ceds_to_mari:
            pth = mari[ceds_to_mari[gas]]
        elif gas in mari:
            pth = mari[gas]
        else:
            pth = mari[fallback]

        # make sure gas name is aligned with gas arg
        print(f"For gas {gas}, using {pth}")
        with xr.open_dataarray(pth) as da:
            return (
                da.drop_vars(["gas"])
                .assign_coords(gas=[gas])
                .transpose(*dim_order, missing_dims="ignore")
                .astype("float32")
                .sel(lat=slice(None, None, -1))
            )

    for gas in gases:
        da = convert_mariteam_to_ceds(mari, gas)
        da.to_netcdf(
            settings.proxy_path / f"shipping_{gas}.nc",
            encoding={"emissions": settings.encoding},
        )


mariteam_shipping()

# %% [markdown]
# # CDR
#
# We provide proxies for several CDR technologies:
#
# 1. OAE CDR uses a full ocean map (together with the country indexraster this results in OAE being applied equally to within country's EEZ)
# 2. DACCS CDR incorporates renewable potentials and CO2 storage potentials
# 3. Industry CDR uses the composition of renewables, CO2 storage and industry co2 emissions
#

# %%
# ind co2 defines the exact grid and other dimensions
ind_co2 = (
    xr.open_dataset(settings.proxy_path / "anthro_CO2.nc").sel(sector="IND")
).emissions
ind_co2

# %%
ind_co2_dimensions = xr.ones_like(ind_co2.drop_vars("sector"))
ind_co2_seasonality = ind_co2.sum(["gas", "year"])
ind_co2_seasonality /= ind_co2_seasonality.sum(["lat", "lon"]).mean("month")

# %% [markdown]
# ## OAE CDR and emissions
#

# %% [markdown]
# Rasterize natural earth ocean shape to proxy grids.

# %%
rasterize = pt.Rasterize(
    shape=(ind_co2.sizes["lat"], ind_co2.sizes["lon"]),
    coords={"lat": ind_co2.coords["lat"], "lon": ind_co2.coords["lon"]},
)
rasterize.read_shpf(
    pio.read_dataframe(
        settings.gridding_path / "non_ceds_input" / "ne_10m_ocean"
    ).reset_index(),
    idxkey="index",
)
oae_cdr = (
    rasterize.rasterize(strategy="weighted", normalize_weights=False)
    .sel(index=0, drop=True)
    .assign_coords(gas="CO2", sector="OAE_CDR")
    * ind_co2_dimensions
)

# %%
plot_map(oae_cdr.sel(year=2050, month=1).assign_attrs(long_name="OAE CDR emissions"))

# %% [markdown]
# ## DACCS and Industrial CDR
#
# Combine renewable potential from GaSP, Global Wind and Solar Atlas with CO2 storage potential
#

# %%
renewable_potential = gu.Raster(
    settings.gridding_path / "renewable_potential/renewable_potential.tiff"
)


# %%
def read_co2_storage_potential(smooth=True):
    co2_storage_potential = gu.Raster(
        settings.gridding_path / "co2_storage_potential/LOW_05.tif"
    )

    # Has no nodata value set, which defaults to 1e20. an explicit -1 is easier to track
    co2_storage_potential.set_nodata(-1)

    if not smooth:
        return co2_storage_potential

    # Transform into platecarree which is given in units of meter
    crs_platecarree = rio.CRS.from_authority("ESRI", 54001)

    # Calculate dst bbox of the transformation
    transform, width, height = rio.warp.calculate_default_transform(
        co2_storage_potential.crs,
        crs_platecarree,
        co2_storage_potential.width,
        co2_storage_potential.height,
        *co2_storage_potential.bounds,
    )
    bounds = rio.coords.BoundingBox(
        *rio.transform.array_bounds(height, width, transform)
    )
    co2_storage_potential_pc = co2_storage_potential.reproject(
        crs=crs_platecarree, grid_size=(width, height), bounds=bounds
    )
    co2_storage_potential_pc_smooth = gu.Raster.from_array(
        gaussian_filter(
            co2_storage_potential_pc.data,
            sigma=(
                200_000
                / abs(transform.a),  # use 200km stddev for gaussian kernel on both axes
                200_000 / abs(transform.e),
            ),
            mode="wrap",
        ),
        transform,
        crs_platecarree,
        nodata=-1,
    )
    co2_storage_potential_smooth = co2_storage_potential_pc_smooth.reproject(
        co2_storage_potential
    )
    return co2_storage_potential_smooth


co2_storage_potential_smooth = read_co2_storage_potential()
daccs_potential = renewable_potential * co2_storage_potential_smooth

# %%
daccs_potential = gu_to_xarray(daccs_potential, ind_co2, "emissions")

# %%
plot_map(
    gu_to_xarray(renewable_potential, ind_co2, "emissions").assign_attrs(
        long_name="Renewable potential"
    )
)

# %%
plot_map(
    gu_to_xarray(co2_storage_potential_smooth, ind_co2, "emissions").assign_attrs(
        long_name="CO2 storage potential (in proximity)"
    )
)

# %%
plot_map(
    daccs_potential.assign_attrs(
        long_name="Renewable and CO2 storage potential",
        units="MW GtCO2 m-2",
    ),
    title="DACCS suitability",
)

# %%
# industry CDR is composition of daccs potential and availability of industrial co2 emissions
ind_cdr = (daccs_potential * ind_co2).assign_coords(sector="IND_CDR")

# %%
plot_map(
    ind_cdr.sel(year=2050, month=1).assign_attrs(
        long_name="Renewable, CO2 storage potential and Industry emissions",
    ),
    title="Industry CDR emissions",
)

# %%
missing_countries(ind_cdr.sel(month=1, year=2050, gas="CO2"))

# %%
# dac cdr as non-seasonal daccs potential (if we find an easy way how to, we might want to add a renewable seasonality)
dac_cdr = (daccs_potential * ind_co2_dimensions).assign_coords(sector="DAC_CDR")

# %%
missing_countries(dac_cdr.sel(month=1, year=2050, gas="CO2"))

# %% [markdown]
# # Land-Use States
#
# [LUH2_v2 docs](https://luh.umd.edu/LUH2/LUH2_v2f_README_v6.pdf) has a number of relevant variables
#
#     2.2.1	States:	(units	fraction	of	grid	cell unless	otherwise	specified)
#
#     c3ann: C3 annual crops
#     c3per: C3 perennial crops
#     c4ann: C4 annual crops
#     c4per: C4 perennial crops
#     c3nfx: C3 nitrogen-fixing crops
#
#     secdf: potentially forested secondary land
#
#     secmb: secondary mean biomass density (units: kg C/m^2)
#
# There are new variables for RESCUE however in the management file. Second generation biofuels (`crpbf_total` in LUH2) is now split into: `crpbf2_c3per` and `crpbf2_c4per`. We also have `manaf` which is "managed forest fraction of potentially forested secondary land".
#
#
#     crpbf2_c3per: 2nd generation biofuels in c3 perennials
#     crpbf2_c4per: 2nd generation biofuels in c4 perennials
#     manaf: managed forest fraction of potentially forested secondary land
#
#
# To generate spatial patterns, we average over the last 30 years of the provided data to estimate potentials in a high mitigation scenario.
#

# %%
fname_states = "multiple-states_input4MIPs_landState_RESCUE_PIK-MAgPIE-4-7-RESCUE-dir-v2p0-PkBudg500-OAE-off-2023.12.8_gn_1995-2100.nc"
ds_s = xr.open_dataset(
    settings.gridding_path / "lu_gridded_files" / fname_states, decode_times=False
).rename(longitude="lon", latitude="lat")
ds_s

# %%
fname_manage = "multiple-management_input4MIPs_landState_RESCUE_PIK-MAgPIE-4-7-RESCUE-dir-v2p0-PkBudg500-OAE-off-2023.12.8_gn_1995-2100.nc"
ds_m = xr.open_dataset(
    settings.gridding_path / "lu_gridded_files" / fname_manage, decode_times=False
).rename(longitude="lon", latitude="lat")
ds_m

# %%
nperiods = 3
time = range(-1, -1 - nperiods, -1)

_m = ds_m.isel(time=time)
_s = ds_s.isel(time=time)

types = [
    ("crpbf2_c3per", "c3per"),
    ("crpbf2_c4per", "c4per"),
    ("crpbf_c3per", "c3per"),
    ("crpbf_c4per", "c4per"),
    ("crpbf_c3ann", "c3ann"),
    ("crpbf_c4ann", "c4ann"),
    ("crpbf_c3nfx", "c3nfx"),
]
beccs_potential = (
    xr.concat(
        (
            (_m[m_type] * _s[s_type]).assign_coords({"type": m_type})
            for m_type, s_type in types
        ),
        dim="type",
    )
    .sum(dim="type")
    .mean(dim="time")
    .interp_like(ind_co2)
    .fillna(0.0)
)
plot_map(beccs_potential, "BECCS potential")

# %%
ar_potential = (
    (ds_m["manaf"] * ds_s["secdf"])
    .isel(time=time)
    .mean(dim="time")
    .clip(min=0)
    .fillna(0.0)
    .interp_like(ind_co2)
)
plot_map(ar_potential, "A/R Potential per Grid Cell")

# %% [markdown]
# # Combine and Save
#

# %%
da = (
    xr.concat(
        [
            ind_cdr,
            oae_cdr,
            # oae_co2, # Part of other emissions
            dac_cdr,
            (beccs_potential * ind_co2_dimensions).assign_coords(sector="BECCS"),
            (ar_potential * ind_co2_dimensions).assign_coords(sector="A/R"),
        ],
        dim="sector",
    )
    .fillna(0.0)
    .transpose(*dim_order, missing_dims="ignore")
    .astype("float32")
)

# %%
da.to_netcdf(
    settings.proxy_path / "CDR_CO2.nc",
    encoding={da.name: settings.encoding},
)
