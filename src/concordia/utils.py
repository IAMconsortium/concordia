from __future__ import annotations

import logging
from collections.abc import Sequence
from functools import reduce
from itertools import chain, product
from pathlib import Path
from typing import TYPE_CHECKING, TypeAlias

import dask.distributed as dd
import numpy as np
import pandas as pd
import pycountry
from attrs import define
from colorlog import ColoredFormatter
from IPython.core.magic import Magics, cell_magic, magics_class
from pandas import DataFrame, isna
from pandas.api.types import is_iterator, is_list_like
from pandas_indexing import concat, isin


if TYPE_CHECKING:
    from typing_extensions import Self

    from .settings import Settings


logger = logging.getLogger(__name__)

Pathy: TypeAlias = str | Path


@magics_class
class CondordiaMagics(Magics):
    @cell_magic
    def execute_or_lazy_load(self, line, cell):
        """Evaluates first line argument.

        If True, executes cell, otherwise executes remaining arguments
        """
        parts = line.split("#")[0].split()
        if self.shell.ev(parts[0]):
            self.shell.run_cell(cell)
        elif len(parts) > 1:
            cmd = " ".join(parts[1:])
            logger.info(f"Running: {cmd}")
            self.shell.run_cell(cmd)
        else:
            return logger.info("Skipped")


@define
class VariableDefinitions:
    data: DataFrame

    @classmethod
    def from_csv(cls, path):
        return cls(
            pd.read_csv(path, index_col=list(range(2))).loc[
                isin(gas=lambda s: ~s.str.startswith("#"))
            ]
        )

    def for_proxy(self, output_variable: str | float) -> Self:
        data = self.data.loc[
            self.data.output_variable.isna()
            if isna(output_variable)
            else (self.data.output_variable == output_variable)
        ]
        return self.__class__(data)

    @property
    def proxies(self):
        return pd.Index(self.data["output_variable"].unique()).dropna()

    @property
    def downscaling(self):
        data = self.data
        subsectors = (
            data.pix.unique("sector")
            .to_series()
            .loc[lambda s: s.str.contains("|", regex=False)]
        )

        return self.__class__(
            data.rename(subsectors.str.split("|").str[0], level="sector")
            .groupby(["gas", "sector"])
            .first()
        )

    @property
    def globallevel(self):
        return self.__class__(self.data.loc[self.data["griddinglevel"] == "global"])

    @property
    def regionlevel(self):
        return self.__class__(self.data.loc[self.data["griddinglevel"] == "region"])

    @property
    def countrylevel(self):
        return self.__class__(self.data.loc[self.data["griddinglevel"] == "country"])

    @property
    def index(self):
        return self.data.index

    @property
    def empty(self):
        return self.data.empty

    @property
    def skip_for_total(self):
        return self.data.index[~self.data.include_in_total]

    def load_data(
        self,
        df: DataFrame,
        levels: list[str] | None = None,
        ignore_undefined: bool = True,
        ignore_missing: bool = False,
        extend_missing: bool | float = False,
        timeseries: bool = True,
        settings: Settings | None = None,
    ):
        """Load data from dataframe.

        Assigns sector/gas and checks correct units.

        Parameters
        ----------
        df : DataFrame
            data
        levels : list of str, optional
            levels to keep, or all if None
        ignore_undefined : bool, default True
            whether to fail if undefined variables exist in `df`
        ignore_missing : bool, default False
            whether to ignore defined variables missing from `df`
        extend_missing : bool or float, default False
            whether to extend_missing with a certain value
        timeseries : bool, default True
            whether data is a timeseries and columns should be cast to int

        Returns
        -------
        DataFrame
            data with sector/gas index levels

        Note
        ----
        Does not check regional availability yet! Also because it would have to
        understand about regionmappings and aggregations then.
        """

        df = df.rename_axis(index=str.lower)
        if timeseries:
            df = df.rename_axis(columns="year").rename(columns=int)
        else:
            df = df.rename(columns=str.lower)

        if "variable" in df.index.names and settings is not None:
            df = df.pix.extract(variable=settings.variable_template, drop=True)

        fill_value = 0 if extend_missing is True else extend_missing

        # Warn about missing or unused data
        def unique_gas_sector_str(index):
            return "\n- " + "\n- ".join(
                index.pix.unique(["gas", "sector"]).map("::".join)
            )

        index, li, ri = df.index.join(self.index, how="outer", return_indexers=True)
        if (li == -1).any() and extend_missing:
            logger.warning(
                f"Variables missing from data (extending with {fill_value}):"
                + unique_gas_sector_str(index[li == -1])
            )
        if (ri == -1).any() and ignore_undefined:
            logger.warning(
                "Unused variables exist in data (ignoring):"
                + unique_gas_sector_str(index[ri == -1])
            )

        if ignore_undefined or ignore_missing:
            index, li, ri = df.index.join(
                self.index,
                how="inner" if ignore_undefined and ignore_missing else "right",
                return_indexers=True,
            )

        if (li == -1).any() and extend_missing is False:
            raise ValueError(
                "Variables missing from data:" + unique_gas_sector_str(index[li == -1])
            )
        if (ri == -1).any():
            raise ValueError(
                "Undefined variables exist in data:"
                + unique_gas_sector_str(index[ri == -1])
            )

        if (li == -1).any():
            # Fix nan-values in levels
            index = index.pix.assign(
                unit=np.where(
                    li != -1, index.pix.project("unit"), self.data["unit"].values[ri]
                ),
            )

        df = pd.DataFrame(
            np.where((li != -1)[:, np.newaxis], df.values[li], fill_value),
            index=index,
            columns=df.columns,
        ).__finalize__(df)
        if timeseries:
            data_units = self.data["unit"].values[ri]
            non_matching_units = df.index.pix.project("unit") != data_units
            if non_matching_units.any():
                errors = (
                    df.index.to_frame(index=False)
                    .loc[
                        non_matching_units,
                        lambda df: df.columns.intersection(
                            ["model", "scenario", "variable", "sector", "gas", "unit"]
                        ),
                    ]
                    .assign(**{"expected unit": data_units[non_matching_units]})
                    .drop_duplicates()
                )
                raise ValueError(
                    "Some variables in the data do not have the correct units:\n"
                    + errors.to_string(index=False)
                )

        if (li == -1).any():
            # Need to expand nan values
            nanlevels = df.index.names.difference(self.index.names).difference(["unit"])

            variations = pd.MultiIndex.from_product(
                chain(
                    np.nonzero(li == -1),
                    (df.pix.unique(level).dropna() for level in nanlevels),
                )
            )
            idx = index[variations.pix.project(None)]
            variations = variations.droplevel(None).pix.assign(
                gas=idx.pix.project("gas"), sector=idx.pix.project("sector")
            )
            df = concat(
                [
                    df.loc[li != -1],
                    df.loc[li == -1].droplevel(nanlevels).pix.semijoin(variations),
                ]
            )

        if levels is not None:
            return df.pix.project(levels)
        return df


@define
class RegionMapping:
    data: pd.Series

    @classmethod
    def concat(cls, rms):
        return cls(pd.concat(rm.data for rm in rms))

    @classmethod
    def from_regiondef(
        cls,
        path,
        country_column="ISO Code",
        region_column="Native Region Code",
        **kwargs,
    ):
        path = Path(path)
        match path.suffix:
            case ".csv":
                df = pd.read_csv(path, **kwargs)
            case ".xlsx":
                df = pd.read_excel(path, **kwargs)
            case suffix:
                raise ValueError(f"Unknown file suffix: {suffix}")

        return cls(
            df.set_index(country_column)[region_column]
            .rename_axis("country")
            .rename(index=str.lower)
            .rename("region")
        )

    def filter(self, countries: Sequence[str] | pd.Index) -> Self:
        return self.__class__(self.data.loc[isin(country=countries)])

    def prefix(self, s: str):
        return self.__class__(s + self.data)

    @property
    def index(self) -> pd.MultiIndex:
        return pd.MultiIndex.from_arrays(
            [self.data.index, self.data.values], names=["country", "region"]
        )

    def aggregate(
        self,
        df: DataFrame,
        level="country",
        agg_func="sum",
        dropna: bool = False,
        keepworld: bool = False,
    ) -> DataFrame:
        if level != "country":
            df = df.rename_axis(index={level: "country"})
        index = self.index
        if keepworld:
            index = index.append(
                pd.MultiIndex.from_tuples([("World", "World")], names=index.names)
            )
        return (
            df.pix.semijoin(index, how="left")
            .groupby(
                [n if n != "country" else "region" for n in df.index.names],
                dropna=dropna,
            )
            .agg(agg_func)
        )


def extend_overrides(
    overrides: pd.Series[str],
    method: str,
    variables: pd.MultiIndex,
    regionmappings: dict[str, RegionMapping],
    gas: Sequence[str] | None = None,
    sector: Sequence[str] | None = None,
    model_baseyear: pd.DataFrame | None = None,
) -> pd.Series[str]:
    regions: pd.Index[str] = pd.Index(
        np.concatenate([rm.data.unique() for rm in regionmappings.values()]),
        name="region",
    ).unique()
    levels = [regions]
    if gas is not None:
        levels.append(pd.Index(gas, name="gas"))
    if sector is not None:
        levels.append(pd.Index(sector, name="sector"))
    methods = pd.Series(
        method, pd.MultiIndex.from_product(levels).join(variables, how="inner")
    )

    if model_baseyear is not None:
        model_iszero = (
            model_baseyear.pix.semijoin(methods.index, how="inner")
            .groupby(methods.index.names)
            .sum()
            == 0
        )
        methods = methods.pix.antijoin(model_iszero.index[model_iszero])

    return concat([overrides, methods.pix.antijoin(overrides.index).rename("method")])


def aggregate_subsectors(df):
    subsectors = (
        df.pix.unique("sector")
        .to_series()
        .loc[lambda s: s.str.contains("|", regex=False)]
    )
    if subsectors.empty:
        return df

    logger.debug(f"Aggregating subsectors: {', '.join(subsectors)}")
    return (
        df.rename(subsectors.str.split("|").str[0], level="sector")
        .groupby(df.index.names)
        .sum()
    )


def make_totals(df):
    original_levels = df.index.names
    if "method" in original_levels:  # need to process harm
        df = df.droplevel("method")
    level = df.index.names
    ret = concat(
        [
            (
                df.loc[~isin(region="World")]  # don"t count aviation
                .groupby(level.difference(["region"]))
                .agg(lambda s: s.sum(skipna=False))
                .pix.assign(region="World", order=level)
            ),
            (
                df.loc[~(isin(sector="Total") | isin(region="World"))]
                .groupby(level.difference(["sector"]))
                .agg(lambda s: s.sum(skipna=False))
                .pix.assign(sector="Total", order=level)
            ),
            (
                df.loc[~isin(sector="Total")]  # don"t count global totals
                .groupby(level.difference(["region", "sector"]))
                .agg(lambda s: s.sum(skipna=False))
                .pix.assign(region="World", sector="Total", order=level)
            ),
        ]
    )
    if "method" in original_levels:  # need to process harm
        ret = ret.pix.assign(method="aggregate", order=original_levels)
    return ret


def add_totals(df, skip_for_total=None):
    reduced = df if skip_for_total is None else df.pix.antijoin(skip_for_total)
    return concat([df, make_totals(reduced)])


def as_seaborn(df: DataFrame, meta: DataFrame | None = None, value_name: str = "value"):
    """Convert multi-indexed time-series dataframe to tidy dataframe.

    Parameters
    ----------
    df : DataFrame
        data in time-series representation with years on columns
    meta : DataFrame, optional
        meta data that is joined before tidying up
    value_name : str
        column name for the values; default "value"

    Returns
    -------
    DataFrame
        Tidy dataframe without index
    """
    df = df.rename_axis(columns="year").stack().rename(value_name)
    if meta is not None:
        df = df.to_frame().join(meta, on=meta.index.names)
    return df.reset_index()


def skipnone(*args):
    if len(args) == 1 and (is_list_like(args[0]) or is_iterator(args[0])):
        args = args[0]
    return [x for x in args if x is not None]


def add_zeros_like(
    df: pd.DataFrame,
    reference: pd.MultiIndex | pd.DataFrame | pd.Series,
    /,
    derive: dict[str, pd.MultiIndex] | None = None,
    **levels: Sequence[str],
):
    """Adds explicit `levels` to `df` as 0 values.

    Remaining levels in `df` not found in `levels` or `derive` are taken from
    `reference` (or its index).

    df : DataFrame
        data in time-series representation with years on columns
    reference : [str]
        expected level labels (like model, scenario combinations)
    derive : dict
        derive labels in a level from a multiindex with allowed combinations
    **levels : [str]
        which labels should be added to df

    Returns
    -------
    DataFrame
        unsorted data with additional zero data

    Note
    ----
    May lead to duplicates!
    """

    if any(len(labels) == 0 for labels in levels.values()):
        return df

    if isinstance(reference, pd.Series | pd.DataFrame):
        reference = reference.index

    if "region" in levels and "region" in reference.names:
        reference = reference[~isin(reference, region="World")]

    if derive is None:
        derive = {}

    target_levels = df.index.names
    index = reference.pix.unique(
        target_levels.difference(levels.keys()).difference(derive.keys())
    )

    return concat(
        [df]
        + [
            pd.DataFrame(
                0,
                index=(
                    reduce(
                        lambda ind, d: ind.join(d, how="left"),
                        derive.values(),
                        index.pix.assign(**dict(zip(levels.keys(), labels))),
                    ).reorder_levels(target_levels)
                ),
                columns=df.columns,
            )
            for labels in product(*levels.values())
        ]
    )


def iso_to_name(x):
    cntry = pycountry.countries.get(alpha_3=x.upper())
    return cntry.name if cntry is not None else x


class DaskSetLogging(dd.diagnostics.plugin.WorkerPlugin):
    """Applies a dictionary logging configuration to workers.

    Note
    ----
    The configuration format is described in
    https://docs.python.org/3/library/logging.config.html#logging-config-dictschema

    Example
    -------
    >>> client = Client()
    >>> client.register_plugin(DaskSetLogging(dict(version=1, root={"level": "INFO"})))
    >>> client.forward_logging()
    """

    def __init__(self, config: dict):
        self.config = config

    def setup(self, worker: dd.Worker):
        logging.config.dictConfig(self.config)


class DaskSetWorkerLoglevel(dd.diagnostics.plugin.WorkerPlugin):
    def __init__(self, loglevel: int):
        self.loglevel = loglevel

    def setup(self, worker: dd.Worker):
        logging.getLogger().setLevel(self.loglevel)


class MultiLineFormatter(ColoredFormatter):
    """Multi-line formatter based on https://stackoverflow.com/a/66855071/2873952"""

    def get_header_length(self, record):
        """
        Get the header length of a given record.
        """
        self.checking_length = True
        length = (
            super()
            .format(
                logging.LogRecord(
                    name=record.name,
                    level=record.levelno,
                    pathname=record.pathname,
                    lineno=record.lineno,
                    msg="<<BOM>>",
                    args=(),
                    exc_info=None,
                )
            )
            .index("<<BOM>>")
        )
        self.checking_length = False
        return length

    def _blank_escape_codes(self):
        return self.checking_length or super()._blank_escape_codes()

    def format(self, record):
        """
        Format a record with added indentation.
        """
        indent = " " * self.get_header_length(record)
        head, *trailing = super().format(record).splitlines(True)
        return head + "".join(indent + line for line in trailing)
