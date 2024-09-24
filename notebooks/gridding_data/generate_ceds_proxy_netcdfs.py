#!/usr/bin/env python

# # Overview
#
# Gridding proxies are provided on a yearly-basis in `input/gridding/proxy-CEDS9`.
# Summing total values leads to <<1 values, indicating that unit transformations may be
# included. It is not clear if this is the kt-to-`<unit>` or Mt-to-`<unit>` transform.
#
# Seasonality (distribution by month) is provided in `input/gridding/seasonality-CEDS9`.
# Summing across months yields values of 1 in each grid cell.
#
# Country raster masks are provided in `input/gridding/mask`. Masks are provided at
# fraciton of country in grid cells.
#
# A blanket mask of negative CO2 values for energy are provided in
# `input/gridding/negCO2`. These masks are raw data and need to be assigned to lat/lon
# values. These are listed in the file `input/gridding/country_location_index_05.csv`,
# which I downloaded from the `emissions_downscaling` repository
#
# # Warnings
#
# It seems that latitude bands are reversed which I have addressed here, but it is good
# to check/confirm this


import itertools
from functools import lru_cache

import dask
import dask.array
import numpy as np
import pandas as pd
import ptolemy as pt
import pyogrio as pio
import pyreadr
import xarray as xr

from concordia.settings import Settings


settings = Settings.from_config("config.yaml", base_path="..", version=None)

dim_order = ["gas", "sector", "level", "year", "month", "lat", "lon"]

sector_mapping = {
    "anthro": ["AGR", "ENE", "IND", "TRA", "RCO", "SLV", "WST"],
    "openburning": ["AWB", "FRTB", "GRSB", "PEAT"],
    "aircraft": ["AIR"],  # NB: proxy issues here, need to address in hackathon
    "shipping": [
        "SHP"
    ],  # NB: this was not split out originally, but 1) we have proxy issues; 2) we will be redoing this in this project
}

template_file = (
    settings.gridding_path
    / "example_files/GCAM4-SSP4-34-SPA4-V25-Harmonized-DB-Sulfur-em-aircraft-anthro_input4MIPs_emissions_CMIP_IAMC-V1_gn_201501-210012.nc"
)
template = xr.open_dataset(template_file)

# For aircraft, only seasonality files are for BC and NOx. We need to check if other aircraft emissions have seasonality in final files or not.
#
# For shipping, seasonality files are available for all species except CO2 and CH4.

ceds_input_gridding_path = settings.gridding_path / "ceds_input/input/gridding"

# # get all files
year_files = pd.read_csv(
    ceds_input_gridding_path / "proxy-CEDS9/proxy_mapping_CEDS9.csv"
)
year_files = year_files.rename(columns={"em": "gas", "proxy_file": "file"}).drop(
    columns=["proxybackup_file"]
)
year_files["file"] = year_files["file"].apply(
    lambda x: ceds_input_gridding_path / f"proxy-CEDS9/{x}.Rd"
)
year_files["gas"] = year_files["gas"].replace({"NMVOC": "VOC"})

season_files = pd.read_csv(
    ceds_input_gridding_path / "seasonality-CEDS9/seasonality_mapping_CEDS9.csv"
)
season_files = season_files.rename(columns={"em": "gas", "seasonality_file": "file"})
season_files["file"] = season_files["file"].apply(
    lambda x: ceds_input_gridding_path / f"seasonality-CEDS9/{x}.Rd"
)

df_files = year_files.merge(
    season_files,
    on=["sector", "gas", "year"],
    how="outer",
    suffixes=["_year", "_season"],
).sort_values(
    ["gas", "sector", "year"]
)  # order matters for padding nans later

# Originally, we were specifically missing (and did not previously process) H2
# from biomass burning. But using the file-based location method above, we now
# should have no missing files.
assert not df_files["file_season"].isnull().any()

df_files = df_files.ffill()
years = [2015] + list(range(2020, 2101, 10))
df_files = df_files[df_files["year"].isin(years)]


# ## Compiling a single country mask file
#
# See [process in original repo](https://github.com/iiasa/emissions_downscaling/blob/79dc01346dd841b0cff82f83df31706d6995c94c/code/parameters/gridding_functions.R#L98):
#
# ```
# proxy_cropped <- proxy[ start_row : end_row, start_col : end_col ]
# ```
#
# **In R, array indexes start at 1**
#
#
# ```
# temperatures <- c(12.9, 13.2, 15.0, 19.2, 21.4, 24.5, 29.5, 24.2, 20.5, 14.5, 10.2, 9.8)
#
# temperatures[2:4]
# >>> 13.2, 15.0, 19.2
# ```
#
# **Rows are latitudes, Columns are longitudes**
def mask_to_ary(row):
    a = pyreadr.read_r(row.file)[f"{row.iso}_mask"]
    lat = template.lat[::-1][row.start_row - 1 : row.end_row]
    lon = template.lon[row.start_col - 1 : row.end_col]
    da = xr.DataArray(
        np.asarray(a, dtype="float32"), coords={"lat": lat, "lon": lon}
    ).reindex(lat=template.lat, lon=template.lon, fill_value=0)
    return da


# ## Generating Country Mask Raster
#
# This function reads in all country masks which are provided as Rdata files and
# translates them to xarray arrays and combines them into a single netcdf file.
def gen_mask():
    print("Generating Mask Raster")
    files = ceds_input_gridding_path.glob("mask/*.Rd")
    df = pd.DataFrame(
        [[f.stem.split("_")[0], f] for f in files],
        columns=["iso", "file"],
    )
    idxs = pd.read_csv(ceds_input_gridding_path / "country_location_index_05.csv")
    data = pd.merge(df, idxs, on="iso")
    mask = xr.concat([mask_to_ary(s) for i, s in data.iterrows()], data.iso)
    return mask


def add_eez_to_mask(mask):
    print("Rasterize and add eez to mask raster")
    rasterize = pt.Rasterize(
        shape=(mask.sizes["lat"], mask.sizes["lon"]),
        coords={"lat": mask.coords["lat"], "lon": mask.coords["lon"]},
    )
    rasterize.read_shpf(
        pio.read_dataframe(
            settings.gridding_path / "non_ceds_input" / "eez_v12.gpkg",
            where="ISO_TER1 IS NOT NULL and POL_TYPE='200NM'",
        )
        .dissolve(by="ISO_TER1")
        .reset_index(names=["iso"]),
        idxkey="iso",
    )
    eez = rasterize.rasterize(strategy="weighted", normalize_weights=False).astype(
        mask.dtype
    )

    eez = eez.assign_coords(iso=eez.indexes["iso"].str.lower()).reindex_like(
        mask, fill_value=0.0
    )

    new_mask = mask + eez
    totals = new_mask.sum("iso")
    return (new_mask / totals).where(totals, 0)


def recombine_mask(mask, include_world=True):
    country_combinations = settings.country_combinations
    for comb, (iso1, iso2) in country_combinations.items():
        mask = xr.concat(
            [
                mask,
                (
                    mask.sel(iso=iso1).fillna(0) + mask.sel(iso=iso2).fillna(0)
                ).assign_coords({"iso": comb}),
            ],
            dim="iso",
        )
    comb_mask = mask.drop_sel(iso=list(itertools.chain(*country_combinations.values())))
    if include_world:
        comb_mask = xr.concat(
            [
                comb_mask,
                comb_mask.sum(dim="iso").assign_coords({"iso": "World"}),
            ],
            dim="iso",
        )
    return comb_mask
    # comb_mask.to_netcdf(settings.gridding_path / "ssp_comb_iso_mask.nc")


def mask_to_indexraster(mask):
    indexraster = pt.IndexRaster.from_weighted_raster(mask.rename(iso="country"))
    return indexraster


def gen_indexraster():
    mask = gen_mask()
    mask.to_netcdf(settings.gridding_path / "ssp_comb_countrymask.nc")
    mask = add_eez_to_mask(mask)
    mask = recombine_mask(mask, include_world=False)
    indexraster = mask_to_indexraster(mask)
    indexraster.to_netcdf(settings.gridding_path / "ssp_comb_indexraster.nc")


#
# Generating sector proxy files
#


def read_r_variable(file):
    print(f"Reading in {file}\n")
    a = pyreadr.read_r(file)[file.stem]
    return np.asarray(a, dtype="float32")[::-1]


@lru_cache
def grid_area_m2():
    return xr.DataArray.from_series(pt.cell_area_from_file(template)).astype("float32")


@lru_cache
def make_year_ary(fname, air=False, waste=False, with_dask=True):
    # special treatement for Waste, see https://github.com/JGCRI/CEDS/wiki/Data_and_Assumptions#proxy-derivation-for-waste-sector
    name = "emissions"
    coords = {"lat": template.lat, "lon": template.lon}
    if air:
        coords["level"] = template.level
    if with_dask:
        a = dask.array.from_delayed(
            dask.delayed(read_r_variable)(fname),
            shape=[len(v) for v in coords.values()],
            dtype="float32",
        )
    else:
        a = read_r_variable(fname)

    # convert to emissions value per m2
    da = xr.DataArray(a, coords=coords, name=name) / grid_area_m2()
    if waste:
        # For any grid cell has a population density greater than the 1000
        # people/sq mile threshold, the population density for that grid cell is
        # fixed to the threshold value, while for any grid cell has a population
        # density less than the threshold, the grid cell keeps its original
        # population density value.
        threshold = 1000 / 2.59e6  # people per m2
        da = xr.where(da > threshold, threshold, da)
    return da


def year_to_ary(row, file_key="file", with_dask=True):
    da = make_year_ary(
        row[file_key], row.sector == "AIR", row.sector == "WST", with_dask=with_dask
    )
    new_coords = {
        "gas": row.gas,
        "sector": row.sector,
        "year": row.year,
    }
    da = da.assign_coords(new_coords)
    da = da.expand_dims(list(new_coords.keys()))
    return da


def read_air(file):
    file = file.with_suffix(".nc")  # we can only read netcdfs for air
    print(f"Reading in {file}\n")
    da = xr.open_dataset(file).var1_1
    # this is supposed to be lat, lon, month, level, based on how other files are treated in season_to_ary
    da = da.transpose(
        "dim1", "dim2", "dim4", "dim3"
    )  # WARNING: very fragile to how ncdfs were made
    return da.data.astype("float32")


@lru_cache
def make_season_ary(fname, air=False, with_dask=True):
    coords = {"lat": template.lat, "lon": template.lon, "month": range(1, 13)}
    name = "seasonality"
    read_func = read_r_variable
    if air:
        read_func = read_air
        coords["level"] = template.level

    if with_dask:
        a = dask.array.from_delayed(
            dask.delayed(read_func)(fname),
            shape=[len(v) for v in coords.values()],
            dtype="float32",
        )
    else:
        a = read_func(fname)
    da = xr.DataArray(a, coords=coords, name=name)
    return da


def season_to_ary(row, file_key="file", with_dask=True):
    da = make_season_ary(row[file_key], row.sector == "AIR", with_dask=with_dask)
    new_coords = {"gas": row.gas, "sector": row.sector}
    da = da.assign_coords(new_coords)
    da = da.expand_dims(list(new_coords.keys()))
    return da


# ## Example Processing
#
# ### multiple years in proxy files
def gen_da_for_sector(gas, sector, with_dask=True):
    files = df_files[(df_files.gas == gas) & (df_files.sector == sector)]
    if len(files.gas.unique()) != 1:
        raise ValueError(f"Expected 1 gas, got {files.gas.unique()}")
    if len(files.sector.unique()) != 1:
        raise ValueError(f"Expected 1 sector, got {files.sector.unique()}")
    if len(files.file_season.unique()) != 1:
        raise ValueError(
            f"Expected 1 seasonality file, got {files.file_season.unique()}"
        )
    yda = xr.concat(
        [
            year_to_ary(row, file_key="file_year", with_dask=with_dask)
            for i, row in files.iterrows()
        ],
        dim="year",
    )
    sda = season_to_ary(files.iloc[0], file_key="file_season", with_dask=with_dask)
    da = yda * sda
    da.name = "emissions"
    return da


# ### Multiple sectors in proxy files
def gen_da_for_gas(gas, sector_key, with_dask=True):
    das = []
    for sector in sector_mapping[sector_key]:
        print(gas, sector)
        da = gen_da_for_sector(gas, sector, with_dask=with_dask)
        das.append(da)
    return xr.concat(das, "sector").transpose(*dim_order, missing_dims="ignore")


# # Full Processing
def full_process(sector_key):
    print(f"Doing full process for {sector_key}")
    sectors = sector_mapping[sector_key]
    sector_files = df_files[df_files.sector.isin(sectors)]
    gases = sector_files.gas.unique()
    for gas in gases:
        da = gen_da_for_gas(gas, sector_key)
        da.to_netcdf(
            settings.proxy_path / f"{sector_key}_{gas}.nc",
            encoding={da.name: settings.encoding},
        )


if __name__ == "__main__":
    gen_indexraster()
    full_process("anthro")
    full_process("openburning")
    full_process("aircraft")
    ## old:
    ## full_process('shipping')
