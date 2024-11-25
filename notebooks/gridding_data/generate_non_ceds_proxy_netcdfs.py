# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.16.4
#   kernelspec:
#     display_name: concordia
#     language: python
#     name: python3
# ---

# %%
import geopandas as gpd
import geoutils as gu
import numpy as np
import ptolemy as pt
import pyogrio as pio
import rasterio as rio
import xarray as xr
from ptolemy.raster import IndexRaster
from pyogrio import read_dataframe
from scipy.ndimage import gaussian_filter

from concordia.rescue.proxy import ReportMissingCountries, gu_to_xarray, plot_map
from concordia.settings import Settings


# %%
settings = Settings.from_config(
    "../config-rescue.yaml",
    local_config_path="../local-config-rescue.yaml",
    version=None,
)
settings.gridding_path, settings.gridding_path.exists()

# %%
dim_order = ["gas", "sector", "level", "year", "month", "lat", "lon"]

# %%
missing_countries = ReportMissingCountries(
    IndexRaster.from_netcdf(settings.gridding_path / "ssp_comb_indexraster.nc")
)


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

# %%
cell_area = xr.DataArray.from_series(pt.cell_area_from_file(ind_co2_dimensions)).astype(
    "float32"
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
        with xr.open_dataset(pth) as da:
            return (
                da.drop_vars(["gas"])
                .assign_coords(gas=[gas])
                .transpose(*dim_order, missing_dims="ignore")
                .astype("float32")
                .sel(lat=slice(None, None, -1))
                / cell_area  # convert to fluxes
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


# %% [markdown]
# ## OAE CDR and emissions
#

# %% [markdown]
# Rasterize eez in 200NM proximity to large land masses ($area >= 2\cdot 10^{4} \,\mathrm{km}^2$)

# %%
natearth = pio.read_dataframe(
    settings.gridding_path
    / "non_ceds_input"
    / "ne_10m_admin_0_countries"
    / "ne_10m_admin_0_countries.shp"
)
eez = pio.read_dataframe(
    settings.gridding_path / "non_ceds_input" / "eez_v12.gpkg",
    where="POL_TYPE='200NM'",
)

# %%
ref = ind_co2.isel(year=0, month=0, gas=0).rio.write_crs(4326)

# %%
crs_platecarree = rio.CRS.from_authority("ESRI", 54001)
bounds = ref.rio.transform_bounds(crs_platecarree)
transform = rio.transform.from_bounds(
    *bounds, width=ref.sizes["lon"], height=ref.sizes["lat"]
)

# %%
natearth_l = natearth.explode().loc[lambda df: df.to_crs("esri:54034").area > 2e10]
largeland = (
    gu.Vector(natearth_l)
    .rasterize(
        crs=crs_platecarree,
        xres=transform.a / 10,
        yres=transform.e / 10,
        bounds=bounds,
        in_value=1,
    )
    .proximity()
)

# %%
eez_mask = gu.Vector(eez).rasterize(largeland, in_value=1)

# %%
oae_mask = (
    gu.Raster(eez_mask & (largeland <= 1_852 * 200))
    .astype(np.float32)
    .reproject(
        crs=rio.CRS.from_epsg(4326),
        grid_size=ref.rio.shape[::-1],
        bounds=rio.coords.BoundingBox(*ref.rio.bounds()),
        resampling=rio.warp.Resampling.average,
    )
)

# %%
oae_cdr = ind_co2_dimensions * gu_to_xarray(oae_mask, ref).where(
    ind_co2["lat"] <= 67.5, 0
).assign_coords(  # restrict to 67.5º like in OceanNET
    gas="CO2", sector="OAE_CDR"
)

# %%
plot_map(
    oae_cdr.sel(year=2050, month=7)
    .squeeze()
    .assign_attrs(long_name="OAE CDR emissions")
)

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
# For BECCS, we are using the LIGNO Biomass potential used for all negative emissions in CMIP6

# %%
ceds_input_gridding_path = settings.gridding_path / "ceds_input/input/gridding"


def cmip6_beccs_potential():
    return (
        xr.open_dataarray(
            ceds_input_gridding_path / "negCO2" / "LIGNOPotentialT_2010.nc", chunks={}
        )
        .rename(latitude="lat", longitude="lon")
        .transpose("time", "lat", "lon")
        .squeeze("time", drop=True)
        .astype("float32")
        .isel(lat=slice(None, None, -1))
        / cell_area  # convert to flux
    )


beccs_potential = cmip6_beccs_potential()

# %%
plot_map(beccs_potential, "BECCS Potential")

# %% [markdown]
# ## Non-urban land mask

# %%
landmask = (
    xr.open_dataarray(settings.gridding_path / "ssp_comb_countrymask.nc")
    .sum("iso")
    .clip(max=1)
)

# %%
land = read_dataframe(settings.gridding_path / "non_ceds_input" / "ne_10m_land")
years = [2020, 2100]


def rasterize_nonurbanland(year, buffer="25km"):
    urban = read_dataframe(
        settings.gridding_path
        / "non-urban_land"
        / "Export_25kmbuffer"
        / f"Buffer_{buffer}_Urb_Boundary_{year}_SSP.shp"
    )
    nonurban = gpd.GeoSeries(
        [land.to_crs(urban.crs).union_all().difference(urban.union_all())],
        crs=urban.crs,
    )

    shape = (landmask.sizes["lat"], landmask.sizes["lon"])
    coords = {"lat": landmask.coords["lat"], "lon": landmask.coords["lon"]}
    raster = xr.DataArray(
        pt.raster.rasterize_pctcover(
            nonurban.to_crs(epsg=4326).iat[0],
            pt.raster.transform_from_latlon(coords["lat"], coords["lon"]),
            shape,
        ),
        dims=["lat", "lon"],
        coords=coords,
    ).where(landmask, 0)
    return raster


nonurb2020 = rasterize_nonurbanland(2020)
nonurb2100 = rasterize_nonurbanland(2100)


# %%
alpha = xr.DataArray(
    np.linspace(0, 1, ind_co2_dimensions.sizes["year"]),
    [ind_co2_dimensions.coords["year"]],
)
nonurban = (1 - alpha) * nonurb2020 + alpha * nonurb2100

# %%
plot_map(nonurban.sel(year=2080), title="Non-urban land")

# %% [markdown]
# # Combine and Save
#

# %%
da = (
    xr.concat(
        [
            ind_cdr,
            oae_cdr,
            dac_cdr,
            (beccs_potential * ind_co2_dimensions).assign_coords(sector="BECCS"),
            (ar_potential * ind_co2_dimensions).assign_coords(sector="A/R"),
            (nonurban * ind_co2_dimensions).assign_coords(
                sector="NONURB"
            ),  # Sort of a fallback
            (landmask * ind_co2_dimensions).assign_coords(sector="LAND"),
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

# %%
