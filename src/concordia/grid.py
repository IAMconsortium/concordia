from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import xarray as xr
from attrs import define

from aneris.grid import Gridded, GriddingContext, Proxy  # noqa: F401

from .utils import VariableDefinitions


logger = logging.getLogger(__name__)


def sector_map(variables):
    return xr.DataArray(
        variables["proxy_sector"]
        .groupby(variables.index.pix.project("sector").str.split("|").str[0])
        .first()  # We assume that sector-splits fall back to the same sector
    )


@define(slots=False)  # cached_property's need __dict__
class ConcordiaProxy(Proxy):
    @classmethod
    def from_variables(
        cls, df, context: GriddingContext, proxy_dir: Path | None = None
    ):
        if isinstance(df, VariableDefinitions):
            df = df.data
        if proxy_dir is None:
            proxy_dir = Path.getcwd()
        name = df["output_variable"].unique().item()
        paths = [proxy_dir / proxy_path for proxy_path in df["proxy_path"].unique()]
        index_mappings = {"sector": sector_map(df)}
        if df.pix.unique("gas").tolist() == ["TA"]:
            index_mappings["gas"] = pd.Series(["CO2"], ["TA"])

        return cls.from_files(
            name, paths, frozenset(df["griddinglevel"]), context, index_mappings
        )
