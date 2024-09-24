from __future__ import annotations

import logging
from collections import namedtuple
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

import dask
import pandas as pd
import ptolemy as pt
import xarray as xr
from attrs import define, field
from pandas_indexing import isin

from .utils import Pathy, VariableDefinitions


if TYPE_CHECKING:
    from collections.abc import Callable


logger = logging.getLogger(__name__)


@dask.delayed
def verify_global_values(
    aggregated, tabular, output_variable, index, abstol=1e-8, reltol=1e-6
) -> pd.DataFrame | None:
    tab_df = tabular.groupby(level=index).sum().unstack("year")
    grid_df = aggregated.to_series().groupby(level=index).sum().unstack("year")
    grid_df, tab_df = grid_df.align(tab_df, join="inner")

    absdiff = abs(grid_df - tab_df)
    if (absdiff >= abstol + reltol * abs(tab_df)).any(axis=None):
        reldiff = (absdiff / tab_df).where(abs(tab_df) > 0, 0)
        logger.warning(
            f"Yearly global totals relative values between grids and global data for ({output_variable}) not within {reltol}:\n"
            f"{reldiff}"
        )
        return reldiff
    else:
        logger.info(
            f"Yearly global totals relative values between grids and global data for ({output_variable}) within tolerance"
        )
        return


def sector_map(variables):
    return xr.DataArray(
        variables["proxy_sector"]
        .groupby(variables.index.pix.project("sector").str.split("|").str[0])
        .first()  # We assume that sector-splits fall back to the same sector
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
        callback: Callable | None = None,
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
    # data is assumed to be given as a flux (beware: CEDS is in absolute terms)
    data: xr.DataArray
    indexrasters: dict[str, pt.IndexRaster]
    cell_area: xr.DataArray
    name: str = "unnamed"

    @classmethod
    def from_variables(cls, df, indexrasters=None, proxy_dir=None, cell_area=None):
        if isinstance(df, VariableDefinitions):
            df = df.data
        if proxy_dir is None:
            proxy_dir = Path.getcwd()
        name = df["output_variable"].unique().item()
        proxy = (
            xr.concat(
                [
                    xr.open_dataarray(
                        proxy_dir / proxy_path,
                        chunks="auto",  # engine="h5netcdf"
                    ).chunk({"lat": -1, "lon": -1})
                    for proxy_path in df["proxy_path"].unique()
                ],
                dim="sector",
            )
            .rename(sector="proxy_sector")
            .sel(proxy_sector=sector_map(df))
            .drop_vars("proxy_sector")
        )

        if (
            proxy.sizes["gas"] == 1
            and len(df.pix.unique("gas")) == 1
            and not (proxy.indexes["gas"] == df.pix.unique("gas")).all()
        ):
            logger.warning(
                "Proxy built for gas %s is being used for gas %s (sectors: %s)",
                proxy.indexes["gas"][0],
                df.pix.unique("gas")[0],
                ", ".join(proxy.indexes["sector"]),
            )
            # We overwrite the gas dimension of the proxy manually
            proxy["gas"] = df.pix.unique("gas")

        griddinglevels = set(df["griddinglevel"])
        if griddinglevels > (set(indexrasters) | {"global"}):
            raise ValueError(
                f"Variables need indexrasters for all griddinglevels: {', '.join(griddinglevels)}"
            )

        if cell_area is None:
            indexraster = next(i for i in indexrasters.values() if i is not None)
            cell_area = indexraster.cell_area.astype(proxy.dtype, copy=False)

        return cls(
            proxy,
            {l: indexrasters.get(l) for l in griddinglevels},
            cell_area=cell_area,
            name=name,
        )

    def reduce_dimensions(self, da):
        da = da.mean("month")
        if "level" in da.dims:
            da = da.sum("level")
        return da * self.cell_area

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

        global_gridded = self.reduce_dimensions(gridded).sum(["lat", "lon"])
        diff = verify_global_values(
            global_gridded, scen, self.name, ("sector", "gas", "year")
        )
        return diff.compute() if compute else diff

    def grid(self, downscaled: pd.DataFrame) -> Gridded:
        scen = self.prepare_downscaled(downscaled)
        (unit,) = downscaled.pix.unique("unit")

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
                gridded.append(self.data * gridded_)

        return Gridded(
            xr.concat(gridded, dim="sector").assign_attrs(units=f"{unit} m-2"),
            downscaled,
            self,
            scen.attrs,
        )
