from __future__ import annotations

import datetime
import ftplib
import logging
from collections.abc import Sequence
from typing import Any

import cf_xarray  # noqa
import dateutil
import numpy as np
import pandas as pd
import xarray as xr
from attrs import define
from cattrs import structure, transform_error
from pandas_indexing import concat, isin
from tqdm.auto import tqdm

from ..settings import FtpSettings


logger = logging.getLogger(__name__)

SECTOR_RENAMES = {
    "Energy Sector": "Energy",
    "Industrial Sector": "Industrial",
    "Transportation Sector": "Transportation",
    "Residential Commercial Other": "Residential, Commercial, Other",
}

SECTOR_ORDERING_DEFAULT = {
    "em_anthro": [
        "Agriculture",
        "Energy",
        "Industrial",
        "Transportation",
        "Residential, Commercial, Other",
        "Solvents Production and Application",
        "Waste",
        "International Shipping",
    ],
    "em_openburning": [
        "Agricultural Waste Burning",
        "Forest Burning",
        "Grassland Burning",
        "Peat Burning",
    ],
}

SECTOR_ORDERING_GAS = {
    "CO2_em_anthro": [
        "Agriculture",
        "Energy",
        "Industrial",
        "Transportation",
        "Residential, Commercial, Other",
        "Solvents Production and Application",
        "Waste",
        "International Shipping",
        "Deforestation and other LUC",
        "OAE Calcination Emissions",
        "CDR Afforestation",
        "CDR BECCS",
        "CDR DACCS",
        "CDR EW",
        "CDR Industry",
        "CDR OAE Uptake Ocean",
    ]
}

ATTRS = {
    "lat": {
        "units": "degrees_north",
        "long_name": "latitude",
        "axis": "Y",
        "realtopology": "linear",
        "standard_name": "latitude",
    },
    "lon": {
        "units": "degrees_east",
        "long_name": "longitude",
        "axis": "X",
        "modulo": 360.0,
        "realtopology": "circular",
        "standard_name": "longitude",
        "topology": "circular",
    },
    "time": {
        "long_name": "time",
        "axis": "T",
        "realtopology": "linear",
        "standard_name": "time",
    },
    "level": {
        "units": "km",
        "long_name": "altitude",
    },
}

DATA_HANDLES = {
    "em_anthro": "anthropogenic",
    "em_AIR_anthro": "aircraft",
    "em_openburning": "openburning",
    "em_removal": "cdr",
}

DS_ATTRS = dict(
    Conventions="CF-1.6",
    activity_id="input4MIPs",
    comment="Gridded emissions produced after harmonization and downscaling as part of the RESCUE project. See https://github.com/IAMconsortium/concordia and https://github.com/iiasa/aneris for documentation on the processes.",
    contact="Matthew J. Gidden (gidden@iiasa.ac.at)",
    data_structure="grid",
    dataset_category="emissions",
    external_variables="gridcell_area",
    frequency="mon",
    further_info_url="https://rescue-climate.eu/",
    grid="0.5x0.5 degree latitude x longitude",
    grid_label="gn",
    license="Creative Commons Attribution-ShareAlike 4.0 International License (https://creativecommons.org/licenses). Further information about this data, including some limitations, can be found via the further_info_url (recorded as a global attribute in this file). The data producers and data providers make no warranty, either express or implied, including, but not limited to, warranties of merchantability and fitness for a particular purpose. All liabilities arising from the supply of the information (including any liability arising in negligence) are excluded to the fullest extent permitted by law.",
    institution="IIASA-PIK",
    institution_id="IIASA",
    mip_era="CMIP7",
    nominal_resolution="50 km",
    realm="atmos",
    references="See: https://github.com/IAMconsortium/concordia and https://rescue-climate.eu/ for references",
    source="Scenarios generated as part of the RESCUE project, see https://rescue-climate.eu/",
    table_id="input4MIPs",
    target_mip="RESCUE",
    product="primary-emissions-data",
    start_date="202001",
    end_date="210012",
)

ALKALINITY_ADDITION_LONGNAME = "Alkalinity Addition as part of OAE"


def convert_to_datetime(ds: xr.Dataset) -> xr.Dataset:
    ds = ds.stack(time=("year", "month"))
    dates = pd.DatetimeIndex(
        ds.indexes["time"].map(
            lambda t: datetime.date(t[0], t[1], 16 if t[1] != 2 else 15)
        )
    )
    return (
        ds.drop_vars(["time", "year", "month"])
        .assign_coords(
            time=xr.IndexVariable(
                "time",
                dates,
                encoding=dict(
                    units="days since 2015-1-1 0:0:0",
                    calendar="noleap",
                    dtype=np.dtype(float),
                ),
            )
        )
        .transpose("time", ...)
    )


def clean_coords(ds):
    return ds.squeeze(drop=True)


def add_bounds(ds, bounds=["lat", "lon", "time", "level"]):
    bounds = list(set(bounds) & set(ds.coords))
    ds = ds.cf.add_bounds(bounds, output_dim="bound")
    ds = ds.reset_coords([f"{b}_bounds" for b in bounds]).rename(
        {f"{b}_bounds": f"{b}_bnds" for b in bounds}
    )
    for b in bounds:
        ds.coords[b].attrs["bounds"] = f"{b}_bnds"
    return ds


def rename_sectors(ds, renames: dict):
    if "sector" not in ds.indexes:
        return ds

    return ds.assign_coords(
        sector=ds.indexes["sector"].map(lambda s: renames.get(s, s))
    )


def ensure_sector_ordering(ds, sector_ordering: Sequence | None):
    if sector_ordering is None:
        return ds

    return ds.reindex(sector=sector_ordering)


def add_sector_mapping(ds, keep_sector_names=True):
    if "sector" not in ds.indexes:
        return ds

    keys = ds.indexes["sector"]
    if not keep_sector_names:
        ds = ds.assign_coords(sector=pd.RangeIndex(len(keys)))

    ds["sector"].attrs.update(
        long_name="sector", ids="; ".join(f"{i}: {k}" for i, k in enumerate(keys))
    )

    return ds


def set_sector_encoding(ds):
    if "sector" not in ds.indexes:
        return ds

    # Saves strings as fixed-length character types (necessary for tools like CDO)
    ds["sector"].encoding["dtype"] = "S1"

    return ds


def update_attrs(ds, attrs):
    for k, v in attrs.items():
        if k in ds:
            ds[k].attrs.update(v)
    return ds


def clean_var(ds, name, gas, handle):
    long_name = (
        f"{gas} {handle} emissions"
        if name != "TA_em_anthro"
        else ALKALINITY_ADDITION_LONGNAME
    )
    ds[name].attrs.update({"cell_methods": "time: mean", "long_name": long_name})
    return ds


def set_var_encoding(ds, name):
    da = ds[name]
    da.encoding.update(
        {
            "zlib": True,
            "complevel": 2,
            "chunksizes": tuple((dict(da.sizes) | dict(time=1)).values()),
            "_FillValue": da.dtype.type(1e20),
        }
    )
    return ds


def ds_attrs(name, model, scenario, version, date):
    gas, rest = name.split("_", 1)
    handle = DATA_HANDLES[rest]
    title = (
        f"Future {handle} emissions of {gas} in {scenario}"
        if name != "TA_em_anthro"
        else f"{ALKALINITY_ADDITION_LONGNAME} in {scenario}"
    )

    extra_attrs = dict(
        source_version=version,
        source_id=f"{DS_ATTRS['institution']}-{model}-{scenario}".replace(" ", "-"),
        variable_id=name,
        creation_date=date,
        title=title,
        reporting_unit=f"Mass flux of {gas}",
    )
    attrs = DS_ATTRS | extra_attrs
    return attrs


class DressUp:
    def __init__(self, version) -> None:
        self.version = version
        self.date = str(datetime.datetime.today())

    def __call__(self, ds, model, scenario, **kwargs):
        vars = list(ds.data_vars)
        assert len(vars) == 1, vars

        name = vars[0]
        gas, rest = name.split("_", 1)
        handle = DATA_HANDLES[rest]

        return (
            ds.pipe(convert_to_datetime)
            .pipe(clean_coords)
            .pipe(add_bounds)
            .pipe(rename_sectors, SECTOR_RENAMES)
            .pipe(
                ensure_sector_ordering,
                SECTOR_ORDERING_GAS.get(name, SECTOR_ORDERING_DEFAULT.get(rest)),
            )
            .pipe(add_sector_mapping)
            .pipe(set_var_encoding, name)
            .pipe(set_sector_encoding)
            .pipe(update_attrs, ATTRS)
            .pipe(clean_var, name, gas, handle)
            .assign_attrs(ds_attrs(name, model, scenario, self.version, self.date))
        )


def ftp_upload(cfg: FtpSettings | dict[str, Any], local_path, remote_path):
    paths = list(local_path.iterdir())

    if not isinstance(cfg, FtpSettings):
        try:
            cfg = structure(cfg, FtpSettings)
        except Exception as exc:
            raise ValueError(", ".join(transform_error(exc, path="cfg"))) from None

    ftp = ftplib.FTP(timeout=30.0)
    ftp.connect(cfg.server, cfg.port)
    ftp.login(cfg.user, cfg.password)

    try:
        if remote_path.as_posix() not in ftp.nlst(remote_path.parent.as_posix()):
            ftp.mkd(remote_path.as_posix())

        ftp.cwd(remote_path.as_posix())
        remote_files = ftp.nlst(remote_path.as_posix())
        for lpath in paths:
            rpath = (remote_path / lpath.name).as_posix()
            lsize = lpath.stat().st_size

            msg = lpath.name
            if rpath in remote_files:
                rtimestamp = dateutil.parser.parse(ftp.voidcmd(f"MDTM {rpath}")[4:])
                ltimestamp = datetime.datetime.fromtimestamp(lpath.lstat().st_mtime)

                rsize = ftp.size(rpath)
                msg += f"\nalready on {remote_path.as_posix()}"
                if rtimestamp < ltimestamp:
                    msg += f",\nbut local file is newer ({rtimestamp} < {ltimestamp})"
                elif rsize != lsize:
                    msg += f",\nbut file size differs ({rsize} != {lsize})"
                else:
                    logger.info(msg + ",\nnot uploading")
                    continue
            else:
                msg += f"\nnot on {remote_path.as_posix()}"

            logger.info(msg + ", \nuploading")
            with (
                open(lpath, "rb") as fp,
                tqdm(total=lsize, unit="B", unit_scale=True, unit_divisor=1024) as pbar,
            ):

                def update_pbar(data):
                    pbar.update(len(data))

                try:
                    ftp.storbinary("STOR " + lpath.name, fp, callback=update_pbar)
                except TimeoutError:
                    # TODO determine whether we need to reconnect in this case
                    pass
                except OSError as exc:
                    if exc.args[0] != "cannot read from timed out object":
                        raise

    finally:
        ftp.close()


@define
class Variants:
    gas: str
    sectors: list[str]
    suffix: str
    variable_template: str

    def copy_from_default(self, data, on="variable"):
        if on == "variable":
            variables = [
                self.variable_template.format(gas=self.gas, sector=sector)
                for sector in self.sectors
            ]
            new_data = data.loc[isin(variable=variables)].rename(
                index=lambda s: s + f" ({self.suffix})", level="variable"
            )
        elif on == "sector":
            new_data = data.loc[isin(sector=self.sectors)].rename(
                index=lambda s: s + f" ({self.suffix})", level="sector"
            )
        else:
            raise ValueError(f"on needs to be either 'variable' or 'sector', not: {on}")

        return concat([data, new_data])

    def rename_suffix(self, data, from_, to, on="variable"):
        if on == "variable":
            renames = {}
            for sector in self.sectors:
                variable = self.variable_template.format(gas=self.gas, sector=sector)
                renames[variable + from_] = variable + to
            return data.rename(index=renames, level="variable")
        elif on == "sector":
            renames = {sector + from_: sector + to for sector in self.sectors}
            return concat(
                [
                    data.loc[~isin(gas=self.gas)],
                    data.loc[isin(gas=self.gas)].rename(index=renames, level=on),
                ]
            )
        else:
            raise ValueError(f"on needs to be either 'variable' or 'sector', not: {on}")

    def rename_from_subsector(self, data, on="variable"):
        return self.rename_suffix(data, f"|{self.suffix}", f" ({self.suffix})", on=on)

    def rename_to_subsector(self, data, on="sector"):
        return self.rename_suffix(data, f" ({self.suffix})", f"|{self.suffix}", on=on)
