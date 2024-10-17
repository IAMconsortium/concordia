"""
Proxy generation helpers.
"""

from __future__ import annotations

import textwrap

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import geoutils as gu
import matplotlib.pyplot as plt
import xarray as xr
from rioxarray import open_rasterio


def gu_to_xarray(raster: gu.Raster, grid_ref=None, name=None):
    da = (
        open_rasterio(raster.to_rio_dataset(), band_as_variable=True)
        .band_1.where(lambda df: df != raster.nodata)
        .rename({"x": "lon", "y": "lat"})
        .drop(["spatial_ref"])
    )
    if grid_ref is not None:
        da = da.reindex_like(
            grid_ref, method="nearest"
        )  # the grid is not exactly the same
    if name is not None:
        da = da.rename(name)
    da.attrs.clear()
    return da


def plot_map(
    da: xr.DataArray,
    title: str | None = None,
    robust: bool = True,
    add_colorbar: bool | None = None,
    borders: bool = False,
    **kwargs,
):
    fig, axis = plt.subplots(
        1, 1, subplot_kw=dict(projection=ccrs.Robinson()), figsize=(12, 6)
    )
    axis.set_global()
    # axis.stock_img()
    axis.coastlines()
    if borders:
        axis.add_feature(cfeature.BORDERS)

    cbar_args = dict(add_colorbar=add_colorbar)
    if add_colorbar is not False:
        cbar_args["cbar_kwargs"] = {"orientation": "horizontal", "shrink": 0.65}

    da.plot(
        ax=axis,
        robust=robust,
        transform=ccrs.PlateCarree(),  # this is important!
        cmap="GnBu",
        **cbar_args,
        **kwargs,
    )
    if title is not None:
        axis.set_title(title)


class ReportMissingCountries:
    def __init__(self, indexraster):
        self.indexraster = indexraster

    def __call__(self, da: xr.DataArray, do_plot: bool = True):
        missing = ~(self.indexraster.aggregate(da) > 0)
        print(
            textwrap.fill(
                f"Missing countries: {', '.join(self.indexraster.index[missing])}"
            )
        )
        if do_plot:
            plot_map(
                self.indexraster.grid(missing.astype(float)).assign_attrs(
                    long_name="Uncovered"
                ),
                robust=False,
                add_colorbar=False,
            )
