from __future__ import annotations

import logging
from collections import namedtuple
from collections.abc import Callable
from functools import cached_property
from pathlib import Path

import dask
import pandas as pd
import ptolemy as pt
import xarray as xr
from attrs import define, field
from pandas_indexing import isin

from .utils import Pathy, VariableDefinitions


logger = logging.getLogger(__name__)


@dask.delayed
def verify_global_values(
    aggregated, tabular, proxy_name, index, abstol=1e-8, reltol=1e-6
) -> pd.DataFrame:
    tab_df = tabular.groupby(level=index).sum().unstack("year")
    grid_df = aggregated.to_series().groupby(level=index).sum().unstack("year")
    grid_df, tab_df = grid_df.align(tab_df, join="inner")

    absdiff = abs(grid_df - tab_df)
    if (absdiff >= abstol + reltol * abs(tab_df)).any(axis=None):
        reldiff = (absdiff / tab_df).where(abs(tab_df) > 0, 0)
        logger.warning(
            f"Yearly global totals relative values between grids and global data for ({proxy_name}) not within {reltol}:\n"
            f"{reldiff}"
        )
        return reldiff
    else:
        logger.info(
            f"Yearly global totals relative values between grids and global data for ({proxy_name}) within tolerance"
        )
        return


def sector_map(variables):
    return dict(
        zip(
            variables["proxy_sector"],
            variables.index.pix.project("sector")
            .str.split("|")
            .str[0],  # We assume that sector-splits fall back to the same sector
        )
    )


Weight = namedtuple("Weight", ["globallevel", "regionlevel", "countrylevel"])


@define
class Gridded:
    data: xr.DataArray
    downscaled: pd.DataFrame
    proxy: Proxy
    meta: dict[str, str] = field(factory=dict)

    def verify(self, compute: bool = True):
        return self.proxy.verify_gridded(self.data, self.downscaled, compute=compute)

    def prepare_dataset(self, callback: Callable | None = None):
        name = self.proxy.name
        ds = self.data.to_dataset(name=name)

        if callback is not None:
            ds = callback(ds, name=name, **self.meta)

        return ds

    def fname(
        self,
        template_fn: str,
        directory: Pathy | None = None,
    ):
        meta = self.meta | dict(name=self.proxy.name)
        fn = template_fn.format(
            **{k: v.replace("_", "-").replace(" ", "-") for k, v in meta.items()}
        )
        if directory is not None:
            fn = Path(directory) / fn
        return fn

    def to_netcdf(
        self,
        template_fn: str,
        callback: Callable = None,
        encoding_kwargs: dict | None = None,
        directory: Pathy | None = None,
        compute: bool = True,
    ):
        ds = self.prepare_dataset(callback)
        encoding_kwargs = (
            ds[self.proxy.name].encoding
            | {
                "zlib": True,
                "complevel": 2,
            }
            | (encoding_kwargs or {})
        )
        return ds.to_netcdf(
            self.fname(template_fn, directory),
            encoding={self.proxy.name: encoding_kwargs},
            compute=compute,
        )


@define(slots=False)  # cached_property's need __dict__
class Proxy:
    data: xr.DataArray
    indexrasters: dict[str, pt.IndexRaster]
    cell_area: xr.DataArray | None
    name: str = "unnamed"

    @classmethod
    def from_variables(
        cls, df, indexrasters=None, proxy_dir=None, cell_area=None, as_flux=None
    ):
        if isinstance(df, VariableDefinitions):
            df = df.data
        if proxy_dir is None:
            proxy_dir = Path.getcwd()
        name = df["proxy_name"].unique().item()
        proxy = xr.concat(
            [
                xr.open_dataarray(
                    proxy_dir / proxy_path, chunks="auto", engine="h5netcdf"
                ).chunk({"lat": -1, "lon": -1})
                for proxy_path in df["proxy_path"].unique()
            ],
            dim="sector",
        )
        sectors = proxy.indexes["sector"].map(sector_map(df))
        if sectors.isna().any():
            unused_sectors = proxy.indexes["sector"][sectors.isna()]
            logger.warn(
                "Proxy %s has unused sectors: %s",
                name,
                ", ".join(unused_sectors),
            )
            proxy = proxy.sel(sector=~sectors.isna())
            sectors = sectors.dropna()
        proxy["sector"] = sectors

        griddinglevels = set(df["griddinglevel"])

        if griddinglevels > (set(indexrasters) | {"global"}):
            raise ValueError(
                f"Variables need indexrasters for all griddinglevels: {', '.join(griddinglevels)}"
            )

        if as_flux is False:
            cell_area = None
        elif cell_area is not None:
            cell_area = cell_area.astype(proxy.dtype, copy=False)
        elif as_flux:
            indexraster = next(i for i in indexrasters.values() if i is not None)
            cell_area = indexraster.cell_area.astype(proxy.dtype, copy=False)

        return cls(
            proxy,
            {l: indexrasters.get(l) for l in griddinglevels},
            cell_area=cell_area,
            name=name,
        )

    @property
    def proxy_as_flux(self):
        da = self.data
        if self.cell_area is not None:
            da = da / self.cell_area
        return da

    def reduce_dimensions(self, da):
        da = da.mean("month")
        if "level" in da.dims:
            da = da.sum("level")
        return da

    @cached_property
    def weight(self):
        proxy_reduced = self.reduce_dimensions(self.data)

        weights = {
            level: (
                proxy_reduced.sum(["lat", "lon"])
                if indexraster is None
                else indexraster.aggregate(proxy_reduced)
            ).chunk(-1)
            for level, indexraster in self.indexrasters.items()
        }
        return Weight(
            **{
                f"{level}level": weights.get(level)
                for level in ("global", "region", "country")
            }
        )

    @staticmethod
    def assert_single_pathway(downscaled):
        pathways = downscaled.pix.unique(["model", "scenario"])
        assert (
            len(pathways) == 1
        ), "`downscaled` is needed as a single scenario, but there are: {pathways}"
        return dict(zip(pathways.names, pathways[0]))

    def prepare_downscaled(self, downscaled):
        meta = self.assert_single_pathway(downscaled)
        downscaled = (
            downscaled.stack("year")
            .pix.semijoin(
                pd.MultiIndex.from_product(
                    [self.data.indexes[d] for d in ["gas", "sector", "year"]]
                ),
                how="inner",
            )
            .pix.project(["gas", "sector", "country", "year"])
            .sort_index()
            .astype(self.data.dtype, copy=False)
        )
        downscaled.attrs.update(meta)
        return downscaled

    def verify_gridded(self, gridded, downscaled, compute: bool = True):
        scen = self.prepare_downscaled(downscaled)

        global_gridded = self.reduce_dimensions(gridded)
        if self.cell_area is not None:
            global_gridded *= self.cell_area
        global_gridded = global_gridded.sum(["lat", "lon"])
        diff = verify_global_values(
            global_gridded, scen, self.name, ("sector", "gas", "year")
        )
        return diff.compute() if compute else diff

    def grid(self, downscaled: pd.DataFrame) -> Gridded:
        scen = self.prepare_downscaled(downscaled)

        def weighted(scen, weight):
            sectors = weight.indexes["sector"].intersection(scen.pix.unique("sector"))
            scen = xr.DataArray.from_series(scen).reindex(sector=sectors, fill_value=0)
            weight = weight.reindex_like(scen)
            return (scen / weight).where(weight, 0).chunk()

        gridded = []
        for level, indexraster in self.indexrasters.items():
            weight = getattr(self.weight, f"{level}level")
            if indexraster is None:
                gridded_ = weighted(
                    scen.loc[isin(country="World")].droplevel("country"), weight
                )
            else:
                gridded_ = indexraster.grid(
                    weighted(scen.loc[isin(country=indexraster.index)], weight)
                ).drop_vars(indexraster.dim)

            if gridded_.size > 0:
                gridded.append(self.proxy_as_flux * gridded_)

        return Gridded(xr.concat(gridded, dim="sector"), downscaled, self, scen.attrs)
