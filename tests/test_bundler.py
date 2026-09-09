"""Tests for the static-site build.

The build's whole claim is that its output needs nothing at the far end, so these check the
shape of what lands on disk rather than mocking the pieces that produce it.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from textual_wasm import bundler

ENTRY = "textual_wasm.app:SpikeApp"
PACKAGE = Path("src/textual_wasm")


def _spec(root: Path) -> bundler.BuildSpec:
    """A build into a fresh directory under `root`."""
    return bundler.BuildSpec(entry=ENTRY, package=PACKAGE, output=root / "site")


def _manifest(result: bundler.BuildResult) -> dict[str, object]:
    return json.loads((result.output / bundler.MANIFEST_NAME).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> bundler.BuildResult:
    output = tmp_path_factory.mktemp("site")
    return bundler.build(bundler.BuildSpec(entry=ENTRY, package=PACKAGE, output=output))


def test_the_page_and_its_manifest_are_written(built: bundler.BuildResult) -> None:
    for name in ("index.html", "main.mjs", bundler.MANIFEST_NAME, bundler.SOURCES_NAME):
        assert (built.output / name).exists(), name


def test_the_entry_script_ships_with_the_build(built: bundler.BuildResult) -> None:
    """The page fetches this at boot; without it the site is a blank terminal."""
    assert (built.output / bundler.ENTRY_NAME).exists()


def test_the_manifest_names_the_app_and_pins_every_runtime(
    built: bundler.BuildResult,
) -> None:
    """Versions live here rather than in the page, so there is one copy of each."""
    manifest = json.loads((built.output / bundler.MANIFEST_NAME).read_text())
    assert manifest["entry"] == ENTRY
    for key in bundler.ASSET_URLS:
        assert manifest[key].startswith("https://"), key
    assert bundler.PYODIDE_VERSION in manifest["pyodideIndexUrl"]


def test_manifest_urls_are_relative_so_the_site_can_be_served_from_a_subpath(
    built: bundler.BuildResult,
) -> None:
    """An absolute path breaks the moment someone deploys under /myapp/."""
    manifest = json.loads((built.output / bundler.MANIFEST_NAME).read_text())
    assert manifest["sourcesUrl"].startswith("./")
    assert manifest["entryUrl"].startswith("./")


def test_python_ships_as_source_for_both_packages(built: bundler.BuildResult) -> None:
    """Sources rather than wheels: it is what lets every runtime load the same files."""
    sources = json.loads((built.output / bundler.SOURCES_NAME).read_text())
    assert "textual_wasm" in sources
    assert "driver.py" in sources["textual_wasm"]
    assert "def " in sources["textual_wasm"]["driver.py"]


def test_stylesheets_travel_with_their_code(built: bundler.BuildResult) -> None:
    """A .tcss left behind fails at mount time, in a browser, rather than at build time."""
    assert ".tcss" in bundler.SOURCE_SUFFIXES


def test_compiled_and_cached_files_are_not_shipped(built: bundler.BuildResult) -> None:
    sources = json.loads((built.output / bundler.SOURCES_NAME).read_text())
    for files in sources.values():
        assert not [name for name in files if "__pycache__" in name or name.endswith(".pyc")]


def test_requirements_come_from_the_projects_own_pins(built: bundler.BuildResult) -> None:
    """One generated list, so a build and a probe install the same closure."""
    assert set(bundler.default_requirements()) <= set(built.requirements)
    assert any(pin.startswith("textual==") for pin in built.requirements)


def test_extra_requirements_are_appended(tmp_path: Path) -> None:
    result = bundler.build(
        bundler.BuildSpec(
            entry=ENTRY,
            package=PACKAGE,
            output=tmp_path / "site",
            requirements=("httpx==0.28.1",),
        )
    )
    assert "httpx==0.28.1" in result.requirements


def test_a_missing_package_is_reported(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        bundler.build(
            bundler.BuildSpec(entry=ENTRY, package=tmp_path / "nope", output=tmp_path / "o")
        )


def test_a_single_file_is_not_a_package(tmp_path: Path) -> None:
    """The entry names a module inside a package; one file cannot rebuild the import path."""
    lonely = tmp_path / "app.py"
    lonely.write_text("")
    with pytest.raises(NotADirectoryError):
        bundler.build(bundler.BuildSpec(entry=ENTRY, package=lonely, output=tmp_path / "o"))


def test_the_title_defaults_to_the_application_class(tmp_path: Path) -> None:
    """The page is the user's. A tab labelled after this project would be branding."""
    manifest = _manifest(bundler.build(_spec(tmp_path)))
    assert manifest["title"] == "SpikeApp"


def test_a_given_title_wins(tmp_path: Path) -> None:
    manifest = _manifest(bundler.build(dataclasses.replace(_spec(tmp_path), title="My App")))
    assert manifest["title"] == "My App"


def test_a_template_overrides_the_shipped_page(tmp_path: Path) -> None:
    """The whole customisation story: what people want to change is a document."""
    template = tmp_path / "template"
    template.mkdir()
    (template / "index.html").write_text("<div id=terminal></div>", encoding="utf-8")

    output = bundler.build(dataclasses.replace(_spec(tmp_path), template=template)).output

    assert (output / "index.html").read_text(encoding="utf-8") == "<div id=terminal></div>"
    # Only the named file is replaced; everything the page needs is still there.
    assert (output / "main.mjs").exists()
    assert (output / bundler.MANIFEST_NAME).exists()


def test_a_missing_template_is_an_error_not_a_silent_default(tmp_path: Path) -> None:
    """Building the default page instead would look like the override was ignored."""
    with pytest.raises(FileNotFoundError):
        bundler.build(dataclasses.replace(_spec(tmp_path), template=tmp_path / "nope"))
