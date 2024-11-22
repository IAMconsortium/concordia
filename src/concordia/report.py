from base64 import b64encode
from collections.abc import Sequence
from io import BytesIO
from itertools import islice
from pathlib import Path
from textwrap import dedent

import matplotlib.pyplot as plt
from dominate import document
from dominate.dom_tag import dom_tag
from dominate.tags import (
    a,
    div,
    h1,
    h2,
    h3,
    h4,
    h5,
    h6,
    img,
    li,
    meta,
    nav,
    script,
    section,
    style,
    ul,
)
from dominate.util import raw
from filelock import FileLock
from joblib import Parallel, delayed
from pandas import DataFrame, Index, Series
from pandas_indexing import isin
from pandas_indexing.core import ensure_multiindex
from slugify import slugify
from tqdm.auto import tqdm


try:
    import plotly.graph_objects as go
    import plotly.io as pio
    from plotly.offline import get_plotlyjs

    has_plotly = True
except ImportError:
    has_plotly = False


try:
    import seaborn as sns

    has_seaborn = True
except ImportError:
    has_seaborn = False


HEADING_TAGS = [h1, h2, h3, h4, h5, h6]


def as_data_url(fig, format="png", close=False):
    buf = BytesIO()
    if isinstance(fig, plt.Axes):
        fig = fig.get_figure()
    elif has_seaborn and isinstance(fig, sns.axisgrid.Grid):
        fig = fig.fig
    fig.savefig(buf, format=format)
    plt.close(fig)

    data = b64encode(buf.getvalue()).decode("utf-8").replace("\n", "")
    return f"data:image/{format};base64," + data


def embed_image(fig, close=True):
    if (
        isinstance(fig, (plt.Axes, plt.Figure))
        or has_seaborn
        and isinstance(fig, sns.axisgrid.Grid)
    ):
        return img(src=as_data_url(fig, close=close))
    elif has_plotly and isinstance(fig, go.Figure):
        return raw(pio.to_html(fig, include_plotlyjs=False, full_html=False))
    else:
        raise NotImplementedError("Has not been implemented, yet")


def find_tag(doc, tag, after=None):
    if not isinstance(doc, dom_tag):
        raise ValueError("Need a dominate tag")
    children = doc.children
    if after is not None:
        children = islice(children, children.index(after) + 1, None)
    for child in children:
        if isinstance(child, tag):
            return child


def find_tag_recursive(doc, tag):
    queue = [doc]
    while queue:
        outer = queue.pop(0)
        if not isinstance(outer, dom_tag):
            continue

        inner = find_tag(outer, tag)
        if inner is not None:
            return (outer, inner)

        queue.extend(outer.children)


def index_tag(outer, tag):
    if tag is None:
        return None
    return outer.children.index(tag)


def build_toc(doc, tag=h1, toc_level=3, compact=False, slug_prefix=""):
    hind = HEADING_TAGS.index(tag) + 1
    toc_list = ul()
    if compact and hind == toc_level:
        toc_list["class"] = "compact"

    res = find_tag_recursive(doc, tag)
    if res is None:
        return
    outer, prev = res

    sections = list(outer.children[: index_tag(outer, prev)])
    while prev:
        title = prev.children[0]
        slug = slug_prefix + slugify(title)
        next = find_tag(outer, tag, prev)

        # wrap in section layer
        sec = section(id=slug)
        sec.add(outer.children[slice(index_tag(outer, prev), index_tag(outer, next))])
        sections.append(sec)

        toc_item = toc_list.add(li(a(title, href=f"#{slug}", __pretty=False)))

        # recurse into section
        if hind < toc_level:
            sub_toc = build_toc(
                sec,
                HEADING_TAGS[hind],
                toc_level,
                compact=compact,
                slug_prefix=slug + "-",
            )
            if sub_toc is not None:
                toc_item.add(sub_toc)

        prev = next

    outer.children = sections
    return toc_list


def add_sticky_toc(
    doc, max_level: int = 3, min_level: int = 1, compact: bool = False
) -> None:
    """Add a sticky table of contents to `doc`

    Searches for heading tags h1 to h6 and wraps them into section tags. The sections
    get slugified ids and a toc on the right side allows scrolling to them quickly.

    Arguments
    ---------
    doc
        Dominate-based document to operate on
    max_level : int, default 3
        Last heading level to include into toc
    min_level : int, default 1
        First heading level
    compact : bool, default False
        Whether to put the last heading level on a single line
    """
    with doc.head:
        script(raw(_jscode), type="text/javascript")
        style(raw(_csscode), type="text/css")

    toc = build_toc(
        doc, tag=HEADING_TAGS[min_level - 1], toc_level=max_level, compact=compact
    )
    doc.add(nav(toc, cls="section-nav"))


def what_changed(next, prev):
    length = len(next)
    if prev is None:
        return range(length)
    for i in range(length):
        if prev[i] != next[i]:
            return range(i, length)


def make_docs(
    plotfunc,
    data: Series | DataFrame,
    files: Series,
    index: Sequence[str] | Index,
    title: str | None = None,
    compact: bool = False,
    directory: Path | None = None,
    use_plotly: bool = False,
    n_jobs: int = 8,
    **kwargs,
) -> Sequence[Path]:
    files = ensure_multiindex(files)

    @delayed
    def make_file(fn, idx):
        sel = isin(**dict(zip(files.index.names, idx)), ignore_missing_levels=True)
        ind = index[sel(index)] if isinstance(index, Index) else index
        doc = make_doc(
            plotfunc,
            data.loc[sel],
            ind,
            title=f"{title}: {' - '.join(idx)}",
            compact=False,
            **kwargs,
        )

        if use_plotly:
            add_plotly_header(doc)

        dir = Path.cwd() if directory is None else directory

        with FileLock(dir / ".lock"):
            with open(dir / fn, "w", encoding="utf-8") as f:
                print(doc, file=f)

        return dir / fn

    try:
        return Parallel(n_jobs=n_jobs, verbose=10)(
            make_file(fn, idx) for idx, fn in files.items()
        )
    finally:
        (directory / ".lock").unlink(missing_ok=True)


def make_doc(
    plotfunc,
    data: Series | DataFrame,
    index: Sequence[str] | Index,
    title=None,
    compact=False,
    **kwargs,
) -> document:
    doc = document(title=title)

    main = doc.add(div())
    prev_idx = None

    if not isinstance(index, Index):
        index = data.pix.unique(index).sort_values()

    index = ensure_multiindex(index)
    for idx in tqdm(index):
        main.add([HEADING_TAGS[i](idx[i]) for i in what_changed(idx, prev_idx)])

        try:
            ax = plotfunc(
                data.loc[isin(**dict(zip(index.names, idx)))],
                **kwargs,
            )
        except ValueError:
            print(f"During {plotfunc.__name__}({dict(zip(index.names, idx))})")
            raise
        main.add(embed_image(ax, close=True))

        prev_idx = idx

    add_sticky_toc(doc, max_level=2, compact=compact)
    return doc


def add_plotly_header(doc):
    if not has_plotly:
        raise RuntimeError("Plotly needs to be installed")
    with doc.head:
        script(raw(get_plotlyjs()), type="text/javascript")


def add_hypothesis(
    doc, ident: str, domain: str = "annotate.climateanalytics.org"
) -> None:
    """Add hypothes.is web client to integrate a shared annotation system.

    Arguments
    ---------
    doc
        Dominate-based document to operate on
    ident : str
        Identifier for sharing annotations across multiple document copies
    domain : str, default "annotate.climateanalytics.org"
        Sort-of an internet domain for grouping documents
        (does not need to exist, see also Notes section)

    Notes
    -----
    All annotators need to create an account and login at https://hypothes.is/.
    For non-public annotations one needs to create a group and share its group
    invite link with all contributors, possibly by including it in the
    document.

    The identifier together with the domain is used to make sure multiple
    copies of the html file share the same annotations. Detailed description of
    document equivalency can be found at
    https://web.hypothes.is/help/how-to-establish-or-avoid-document-equivalence-in-the-hypothesis-system/.
    """
    with doc.head:
        meta(name="dc.identifier", content=ident)
        meta(name="dc.relation.ispartof", content=domain)
        script(**{"async": True, "src": "https://hypothes.is/embed.js"})


# Javascript, CSS and HTML for the Sticky TOC are subject to
# Copyright (c) 2023 by Bramus (https://codepen.io/bramus/pen/ExaEqMJ)
# MIT license.
_jscode = dedent(
    """
    window.addEventListener('DOMContentLoaded', () => {
        const observer = new IntersectionObserver(entries => {
            entries.forEach(entry => {
            const id = entry.target.getAttribute('id');
            if (entry.intersectionRatio > 0) {
                document.querySelector(`nav li a[href="#${id}"]`).parentElement.classList.add('active');
            } else {
                document.querySelector(`nav li a[href="#${id}"]`).parentElement.classList.remove('active');
            }
            });
        });

        // Track all sections that have an `id` applied
        document.querySelectorAll('section[id]').forEach((section) => {
            observer.observe(section);
        });
    });
    """
)

_csscode = dedent(
    """
    html {
        scroll-behavior: smooth;
    }

    body {
        display: grid;
        grid-template-columns: 1fr minmax(18rem, 0.3fr);
        padding-left: 5rem;
        margin: 0 auto;
    }

    body > .section-nav {
        position: sticky;
        top: 0;
        align-self: start;
        justify-self: right;

        height: 100vh;
        overflow: auto;

        padding: 1rem  0.25rem 1rem 0;
        border-left: 1px solid #efefef;
    }

    .section-nav a {
        display: block;
        text-decoration: none;
        padding: .125rem 0;
        color: #ccc;
        transition: all 50ms ease-in-out; /* 💡 This small transition makes setting of the active state smooth */
    }

    .section-nav a:hover,
    .section-nav a:focus {
        color: #666;
    }

    .section-nav li.active > a {
        color: #333;
        font-weight: 500;
    }

    .section-nav ul {
        list-style: none;
        margin: 0;
        padding: 0;
    }
    .section-nav li {
        margin-left: 1rem;
    }

    ul.compact {
        margin-left: 1rem;
    }

    ul.compact li {
        padding-right: .25em;
        display: inline;
        margin: 0;
    }

    ul.compact a {
        display: inline;
        padding: 0;
    }

    * {
        box-sizing: border-box;
    }

    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Roboto", "Oxygen", "Ubuntu", "Cantarell", "Fira Sans", "Droid Sans", "Helvetica Neue", sans-serif;
    }

    h1 {
        font-weight: 300;
    }

"""
)
