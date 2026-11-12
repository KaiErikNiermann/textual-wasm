"""Build the benchmark apps the way an author would, and serve them for the run.

Built through `textual_wasm.bundler.build` - the same call `textual-wasm build` makes - so
what is measured is what ships. The baseline pages are copied in next to the build because
they import the build's own `boot.mjs`: a baseline brought up with a different loader
would measure a different loader.
"""

from __future__ import annotations

import contextlib
import shutil
from collections.abc import Generator, Iterable, Mapping
from pathlib import Path

from textual_wasm.bundler import BuildSpec, background_server, build
from textual_wasm_bench import paths
from textual_wasm_bench.plan import SITE_ENTRIES, Mode, Site


def site_directory(site: Site, mode: Mode) -> Path:
    """Where one site is built."""
    return paths.SCRATCH / "sites" / f"{site}-{mode}"


def build_site(site: Site, mode: Mode) -> Path:
    """Build `site` for `mode` from scratch, baseline pages included."""
    output = site_directory(site, mode)
    if output.exists():
        shutil.rmtree(output)
    build(
        BuildSpec(
            entry=SITE_ENTRIES[site],
            package=paths.APPS,
            output=output,
            worker=mode is Mode.WORKER,
        )
    )
    for page in paths.PAGES.iterdir():
        shutil.copy2(page, output / page.name)
    return output


@contextlib.contextmanager
def serve(modes: Iterable[Mode]) -> Generator[Mapping[tuple[Site, Mode], str]]:
    """Build and serve every site for `modes`, yielding each one's base URL."""
    with contextlib.ExitStack() as stack:
        urls: dict[tuple[Site, Mode], str] = {}
        for mode in modes:
            for site in Site:
                directory = build_site(site, mode)
                urls[site, mode] = stack.enter_context(background_server(directory))
        yield urls
