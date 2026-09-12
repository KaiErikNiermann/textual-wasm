"""Tests for the static-site build.

The build's whole claim is that its output needs nothing at the far end, so these check the
shape of what lands on disk rather than mocking the pieces that produce it.
"""

from __future__ import annotations

import base64
import dataclasses
import json
from pathlib import Path

import pytest

from textual_wasm import bundler
from textual_wasm.doctor.deps import load_catalogue
from textual_wasm.target import EntryError

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
    assert "def " in sources["textual_wasm"]["driver.py"]["data"]


def test_every_file_in_the_package_travels(tmp_path: Path) -> None:
    """Not only the source-like suffixes.

    The earlier rule was an allowlist of extensions, and it failed in the way this project
    exists to catch: an app reading a `data.json` next to its code built cleanly, shipped
    without the file, and raised `FileNotFoundError` in the browser for a path that plainly
    existed on disk.
    """
    package = tmp_path / "carrier"
    (package / "nested").mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "style.tcss").write_text("Static { color: red; }", encoding="utf-8")
    (package / "data.json").write_text('{"k": 1}', encoding="utf-8")
    (package / "notes.md").write_text("# notes", encoding="utf-8")
    (package / "nested" / "table.csv").write_text("a,b\n1,2", encoding="utf-8")

    shipped = bundler._collect_sources(package)  # pyright: ignore[reportPrivateUsage]

    assert set(shipped) == {
        "__init__.py",
        "style.tcss",
        "data.json",
        "notes.md",
        str(Path("nested") / "table.csv"),
    }
    assert shipped["data.json"] == {"encoding": "utf8", "data": '{"k": 1}'}


def test_binary_files_survive_the_journey(tmp_path: Path) -> None:
    """A package may legitimately carry an image, a font or a database.

    JSON cannot hold arbitrary bytes, so these travel base64 - and the encoding is recorded
    per file rather than guessed at the far end.
    """
    package = tmp_path / "binary"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    payload = bytes(range(256))
    (package / "logo.png").write_bytes(payload)

    shipped = bundler._collect_sources(package)  # pyright: ignore[reportPrivateUsage]

    assert shipped["logo.png"]["encoding"] == "base64"
    assert base64.b64decode(shipped["logo.png"]["data"]) == payload


def test_compiled_and_cached_files_are_not_shipped(built: bundler.BuildResult) -> None:
    sources = json.loads((built.output / bundler.SOURCES_NAME).read_text())
    for files in sources.values():
        assert not [name for name in files if "__pycache__" in name or name.endswith(".pyc")]


def test_caches_and_environments_are_not_shipped(tmp_path: Path) -> None:
    """Shipping everything makes the exclusions load-bearing, so they are checked.

    A virtualenv or a node_modules inside a package directory would otherwise be copied into
    the page byte for byte.
    """
    package = tmp_path / "dirty"
    for directory in (".venv", "node_modules", "__pycache__", ".ruff_cache"):
        (package / directory).mkdir(parents=True)
        (package / directory / "junk.py").write_text("junk", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "app.cpython-314.pyc").write_bytes(b"\x00")

    assert set(bundler._collect_sources(package)) == {"__init__.py"}  # pyright: ignore[reportPrivateUsage]


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


def test_the_worker_runtime_ships_with_every_build(built: bundler.BuildResult) -> None:
    """Both entry points and the code they share are always present.

    Shipped unconditionally rather than only for `--worker` builds because the page decides
    which to use from the manifest at runtime: a template that turns the flag on by editing
    `app.json` should not also have to know which files to copy.
    """
    for name in ("boot.mjs", "worker.mjs"):
        assert (built.output / name).exists(), name


def test_a_build_runs_on_the_main_thread_unless_asked(built: bundler.BuildResult) -> None:
    """The default is the mode with fewer moving parts."""
    assert _manifest(built)["worker"] is False


def test_the_worker_flag_reaches_the_page(tmp_path: Path) -> None:
    """The manifest is how `main.mjs` knows to start a worker at all."""
    manifest = _manifest(bundler.build(dataclasses.replace(_spec(tmp_path), worker=True)))
    assert manifest["worker"] is True


def test_a_build_refuses_an_entry_that_cannot_resolve(tmp_path: Path) -> None:
    """The failure this prevents is expensive: it surfaces in a browser after a deploy.

    Every one of these built cleanly before, reported success, and produced a site whose
    only symptom was a traceback on first load.
    """
    for entry in ("nosuchmodule:App", f"{ENTRY.split(':', maxsplit=1)[0]}:Missing"):
        with pytest.raises((EntryError, ModuleNotFoundError)):
            bundler.build(dataclasses.replace(_spec(tmp_path), entry=entry))


def test_a_build_refuses_an_entry_that_is_not_an_app(tmp_path: Path) -> None:
    """Resolving is not enough; it has to name something runnable."""
    with pytest.raises(EntryError, match="not a Textual App"):
        bundler.build(dataclasses.replace(_spec(tmp_path), entry="textual_wasm.bundler:BuildSpec"))


def test_verification_can_be_turned_off(tmp_path: Path) -> None:
    """For an app whose module body imports `js` or `pyodide`, which exist only in the
    runtime it is being built for - the one case where importing to check is not possible."""
    result = bundler.build(
        dataclasses.replace(_spec(tmp_path), entry="nosuchmodule:App", verify_entry=False)
    )
    assert (result.output / bundler.MANIFEST_NAME).exists()


def test_the_app_need_not_be_importable_from_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`build` is given the package directory, so that is where the entry is resolved from.

    Verifying against the working directory instead broke the docs site, which builds every
    demo from the repository root while each app lives under `examples/`.
    """
    package = tmp_path / "sources" / "away_app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "app.py").write_text(
        "from textual.app import App\n\n\nclass Away(App[None]):\n    pass\n", encoding="utf-8"
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = bundler.build(
        bundler.BuildSpec(entry="away_app.app:Away", package=package, output=tmp_path / "site-away")
    )

    assert result.notes == ()
    assert (result.output / bundler.MANIFEST_NAME).exists()


def test_a_closure_pyodide_cannot_install_is_refused_before_the_site_is_written(
    tmp_path: Path,
) -> None:
    """The failure this prevents is a build that reports success and dies in someone's browser.

    `pandas<=2.2.3` is not hypothetical - it is `textual-pandas`, which fails under micropip
    for exactly this reason, and Pyodide's pandas is 3.0.2.
    """
    try:
        load_catalogue()
    except FileNotFoundError:
        pytest.skip("no vendored Pyodide runtime to classify against")

    output = tmp_path / "site"
    spec = dataclasses.replace(_spec(tmp_path), requirements=("pandas<=2.2.3",))
    with pytest.raises(bundler.UnsatisfiableRequirementsError) as caught:
        bundler.build(spec)
    assert [item.name for item in caught.value.conflicts] == ["pandas"]
    # Nothing at all, not merely no manifest: the check needs no part of the build to have
    # run, so a refusal that scatters assets around is a directory someone has to clean up.
    assert not output.exists(), f"a refused build left files behind: {list(output.iterdir())}"


def test_the_check_can_be_turned_off(tmp_path: Path) -> None:
    """An escape hatch, because the check reads a lock file that may not describe the runtime
    a given build actually loads."""
    result = bundler.build(
        dataclasses.replace(
            _spec(tmp_path), requirements=("pandas<=2.2.3",), check_dependencies=False
        )
    )
    assert not result.dependencies_checked
    assert (result.output / bundler.MANIFEST_NAME).exists()


def test_an_unchecked_build_says_so_rather_than_reporting_a_clean_one(tmp_path: Path) -> None:
    """`dependencies_checked` is the difference between "nothing wrong" and "nothing looked"."""
    result = bundler.build(dataclasses.replace(_spec(tmp_path), check_dependencies=False))
    assert not result.dependencies_checked
