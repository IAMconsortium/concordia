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
# %load_ext autoreload
# %autoreload 2

# %%
from functools import reduce
from subprocess import run

import pandas as pd
import plotly.express as px
import plotly.io as pio
import seaborn as sns
from dominate import document
from dominate.tags import div
from filelock import FileLock
from joblib import Parallel, delayed
from pandas_indexing import concat, isin, ismatch
from tqdm import tqdm

from concordia import add_sticky_toc, embed_image
from concordia.report import HEADING_TAGS, add_plotly_header
from concordia.rescue import utils as rescue_utils
from concordia.settings import Settings
from concordia.utils import RegionMapping


pio.templates.default = "ggplot2"

# %%
version_old = "2024-04-25"
version = "2024-08-19"

# %%
settings = Settings.from_config(version=version)

# %%
smoothed = rescue_utils.Variants(
    "CO2",
    ["Deforestation and other LUC", "CDR Afforestation", "Net LUC"],
    suffix="Smoothed",
    variable_template=settings.variable_template,
)

# %%
out_path = settings.out_path / settings.version

# %%
regionmappings = {}

for model, kwargs in settings.regionmappings.items():
    regionmapping = RegionMapping.from_regiondef(**kwargs)
    regionmapping.data = regionmapping.data.pix.aggregate(
        country=settings.country_combinations, agg_func="last"
    )
    regionmappings[model] = regionmapping


# %%
def add_net_luc(df, suffix=""):
    df = df.rename({"Aggregate - Agriculture and LUC": "Deforestation and other LUC"})
    positive = df.loc[isin(sector="Deforestation and other LUC" + suffix)]
    negative = df.loc[isin(sector="CDR Afforestation" + suffix)]

    new_df = [df]
    if "World" not in negative.pix.unique("region"):
        negative = (
            negative.groupby(negative.index.names.difference(["region"]))
            .sum()
            .pix.assign(region="World")
        )
        new_df.append(negative)
    assign = {"sector": "Net LUC" + suffix}
    if "method" in df.index.names:
        assign["method"] = "aggregated"
    new_df.append(positive.pix.add(negative, join="left", assign=assign))

    return concat(new_df)


# %%
def aggregate_subsectors(df):
    subsectors = (
        df.pix.unique("sector")
        .to_series()
        .loc[lambda s: s.str.contains("|", regex=False)]
    )
    if subsectors.empty:
        return df

    df_agg = df.pix.assign(method="aggregated") if "method" in df.index.names else df
    return concat(
        [
            df,
            df_agg.pix.aggregate(
                sector=subsectors.index.groupby(subsectors.str.split("|").str[0]),
                mode="return",
            ),
        ]
    )


def add_variant(df, variant: rescue_utils.Variants):
    if df.pix.unique("sector").str.endswith(f"|{variant.suffix}").any():
        df = smoothed.rename_from_subsector(df, on="sector")
    else:
        df = smoothed.copy_from_default(df, on="sector")
    return add_net_luc(df, suffix=f" ({smoothed.suffix})")


def prepare_data(df):
    return (
        df.dropna(how="all", axis=1)
        .pipe(add_net_luc)
        .pipe(add_variant, smoothed)
        .pipe(aggregate_subsectors)
        .pipe(smoothed.rename_to_subsector, on="sector")
    )


def read_version(version, variable_template):
    data = (
        pd.read_csv(
            settings.out_path / version / f"harmonization-{version}.csv",
            index_col=list(range(5)),
            engine="pyarrow",
        )
        .rename_axis(index=str.lower)
        .rename(columns=int)
        .loc[
            ismatch(scenario=["*-Baseline", "*-PkBudg_cp2300-OAE_off", "*-PkBudg500-*"])
            | isin(model="Historic")
        ]
    )
    model = data.pix.extract(
        variable=variable_template + "|Unharmonized", drop=True
    ).pipe(prepare_data)
    harm = data.pix.extract(
        variable=variable_template + "|Harmonized|{method}", drop=True
    ).pipe(prepare_data)
    hist = (
        data.loc[isin(model="Historic")]
        .pix.extract(variable=variable_template, drop=True)
        .pix.dropna(subset="region")
        .pipe(prepare_data)
    )

    return model, harm, hist


# %%
model, harm, hist = read_version(version, settings.variable_template)

# %%
if version_old is not None:
    model_old, harm_old, hist_old = read_version(
        version_old, settings.variable_template
    )


# %%
def extract_sector_gas(df):
    return concat(
        [
            df.pix.extract(
                variable="CEDS+|9+ Sectors|Emissions|{gas}|{sector}|Unharmonized",
                drop=True,
            ),
            df.pix.extract(
                variable="CEDS+|9+ Sectors|Emissions|{gas}|Unharmonized", drop=True
            ).pix.assign(sector="Total"),
        ]
    )


# %%
# TODO currently only works for a single model
(model_name,) = model.pix.unique("model")
regionmapping = regionmappings[model_name]

# %%
cmip6_hist = (
    pd.read_csv(
        settings.data_path / "cmip6_history.csv",
        index_col=list(range(5)),
        engine="pyarrow",
    )
    .rename_axis(index=str.lower)
    .rename(index={"Mt CO2-eq/yr": "Mt CO2eq/yr"}, level="unit")
    .rename(columns=int)
    .pipe(extract_sector_gas)
    .pix.assign(model="CEDS", scenario="CMIP6")
    .pix.aggregate(region=settings.country_combinations)
    .pipe(
        regionmapping.aggregate,
        level="region",
        keepworld=True,
        dropna=True,
    )
)

# %%
# Recompute regional CO2 total (since they include wrongly fire emissions)
cmip6_hist = (
    concat(
        [
            cmip6_hist.loc[
                ~(isin(gas="CO2", sector="Total") & ~isin(region="World"))
                & ~isin(gas="CO2", sector="Aggregate - Agriculture and LUC")
            ],
            cmip6_hist.loc[
                isin(gas="CO2") & ~isin(sector="Total") & ~isin(region="World")
            ]
            .pix.assign(sector="Total")
            .groupby(cmip6_hist.index.names)
            .sum(),
            cmip6_hist.loc[
                isin(gas="CO2", sector="Aggregate - Agriculture and LUC")
            ].pix.assign(sector="Net LUC"),
        ]
    )
    .sort_index()
    .pipe(smoothed.copy_from_default, on="sector")
    .pipe(smoothed.rename_to_subsector, on="sector")
)

# %%
hist = concat([hist, cmip6_hist])


# %%
def plot_harm(sel, scenario=None, levels=["gas", "sector", "region"], useplotly=False):
    model_sel = sel if scenario is None else sel & ismatch(scenario=scenario)
    h = harm.loc[model_sel]

    data = {}

    data[version] = concat(
        dict(
            CEDS=hist.loc[sel & isin(scenario="Synthetic (GFED/CEDS/Global)")],
            CMIP6=hist.loc[sel & isin(scenario="CMIP6")],
            Unharmonized=model.loc[model_sel],
            Harmonized=h.droplevel("method"),
        ),
        keys="pathway",
    ).loc[:, 2000:]

    if version_old is not None:
        h_old = harm_old.loc[model_sel]
        data[version_old] = concat(
            dict(
                CEDS=hist_old.loc[sel & isin(scenario="Synthetic (GFED/CEDS/Global)")],
                Unharmonized=model_old.loc[model_sel],
                Harmonized=h_old.droplevel("method"),
            ),
            keys="pathway",
        ).loc[:, 2000:]

    data = concat(data, keys="version")

    non_uniques = [lvl for lvl in levels if len(h.pix.unique(lvl)) > 1]
    if not non_uniques:
        non_uniques = ["region"]
        data = data.pix.semijoin(h.pix.unique(levels), how="right")

    (non_unique,) = non_uniques
    methods = pd.Series(h.index.pix.project("method"), h.index.pix.project(non_unique))

    if useplotly:
        g = px.line(
            data.pix.to_tidy(),
            x="year",
            y="value",
            color="pathway",
            style="version",
            facet_col=non_unique,
            facet_col_wrap=4,
            labels=dict(value=data.pix.unique("unit").item(), pathway="Trajectory"),
        )
        g.update_yaxes(matches=None)

        def add_method(text):
            name, label = text.split("=")
            return f"{name} = {label}, method = {methods[label]}"

        g.for_each_annotation(lambda a: a.update(text=add_method(a.text)))
        return g

    num_facets = len(data.pix.unique(non_unique))
    multirow_args = dict(col_wrap=4, height=2, aspect=1.5) if num_facets > 1 else dict()
    g = sns.relplot(
        data.pix.to_tidy(),
        kind="line",
        x="year",
        y="value",
        col=non_unique,
        hue="pathway",
        style="version",
        facet_kws=dict(sharey=False),
        legend=True,
        **multirow_args,
    ).set(ylabel=data.pix.unique("unit").item())
    for label, ax in g.axes_dict.items():
        ax.set_title(f"{non_unique} = {label}, method = {methods[label]}", fontsize=9)
    return g


# %%
plot_harm(
    isin(region="CHA", sector="Energy Sector", gas="CH4"),
    scenario="RESCUE-Tier1-Direct-*-PkBudg500-OAE_on",
)
# plt.legend(labels=["CEDS", "CMIP6", "Unharmonized", "Harmonized"], frameon=False)

# %%
g = plot_harm(
    isin(sector="Total", gas="CO2"),
    scenario="RESCUE-Tier1-Direct-*-PkBudg500-OAE_on",
    useplotly=False,
)

# %%
model.pix.unique("sector")

# %%
g = plot_harm(
    isin(sector="Deforestation and other LUC|Smoothed", gas="CO2"),
    scenario="RESCUE-Tier1-Direct-*-PkBudg500-OAE_on",
    useplotly=False,
)

# %%
g = plot_harm(
    isin(sector="Net LUC|Smoothed", gas="CO2"),
    scenario="RESCUE-Tier1-Sensitivity-*-Baseline",
    useplotly=False,
)

# %%
g = plot_harm(
    isin(sector="Net LUC", gas="CO2"),
    scenario="RESCUE-Tier1-Sensitivity-*-Baseline",
    useplotly=False,
)

# %% [markdown]
# # Make Comparison Notebooks


# %%
def what_changed(next, prev):
    length = len(next)
    if prev is None:
        return range(length)
    for i in range(length):
        if prev[i] != next[i]:
            return range(i, length)


# %%
def make_doc(order, scenario=None, compact=False, useplotly=False):
    if scenario is None:
        ((m, s),) = harm.pix.unique(["model", "scenario"])
    else:
        m = harm.pix.unique("model").item()
        s = scenario

    index = harm.index.pix.unique(order).sort_values()
    doc = document(title=f"Harmonization results: {m} - {s}")

    main = doc.add(div())
    prev_idx = None
    for idx in tqdm(index):
        main.add([HEADING_TAGS[i](idx[i]) for i in what_changed(idx, prev_idx)])

        try:
            ax = plot_harm(
                isin(**dict(zip(index.names, idx)), ignore_missing_levels=True),
                scenario=scenario,
                useplotly=useplotly,
            )
        except ValueError:
            print(
                f"During plot_harm(isin(**{dict(zip(index.names, idx))}, ignore_missing_levels=True), {scenario=})"
            )
            raise
        main.add(embed_image(ax, close=True))

        prev_idx = idx

    add_sticky_toc(doc, max_level=2, compact=compact)
    if useplotly:
        add_plotly_header(doc)
    return doc


# %%
def shorten(scenario):
    return reduce(
        lambda scen, pref: scen.removeprefix(pref),
        [
            "RESCUE-Tier1-Direct-*-",
            "RESCUE-Tier1-Extension-*-",
            "RESCUE-Tier1-Sensitivity-*-",
        ],
        scenario,
    )


# %%
files = [
    out_path / f"harmonization-{version}.csv",
    out_path / f"harmonization-{version}-splithfc.csv",
]


# %%
# for scenario in harm.pix.unique("scenario").str.replace(version, "*"):
#     fn = out_path / f"harmonization-{version}-single-{shorten(scenario)}.html"
#     with open(fn, "w", encoding="utf-8") as f:
#         print(
#             make_doc(
#                 order=["gas", "sector", "region"], scenario=scenario, compact=False
#             ),
#             file=f,
#         )
#     files.append(fn)


# %%
def make_scenario_facets(scenario, useplotly=False):
    suffix = "-plotly" if useplotly else ""
    fn = out_path / f"harmonization-{version}-facet-{shorten(scenario)}{suffix}.html"

    lock = FileLock(out_path / ".lock")
    doc = make_doc(order=["gas", "sector"], scenario=scenario, useplotly=useplotly)

    with lock:
        with open(fn, "w", encoding="utf-8") as f:
            print(doc, file=f)
    return fn


files.extend(
    Parallel(n_jobs=min(10, len(harm.pix.unique("scenario"))), verbose=10)(
        delayed(make_scenario_facets)(scenario)
        for scenario in harm.pix.unique("scenario").str.replace(version, "*")
    )
)

# %%
files

# %%
# !open {files[4]}

# %%
for fn in files:
    run(["aws", "s3", "cp", fn, f"s3://rescue-task1.3/harmonization/{version}/"])

# %%
