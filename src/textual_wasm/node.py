"""Run the packaged JavaScript harnesses, when the machine can.

Two legs of a check - Pyodide under Node and the app in a real browser - need a JavaScript
runtime and two npm packages that this project cannot install on the user's behalf. So they
are *optional*, and the interesting design constraint is what happens when they are missing:
a check that fails because a tool is absent teaches people to ignore its result, and a check
that quietly drops half its legs is worse. Everything here exists to make "not run" a
reported outcome with a fix attached, rather than either.

Bare `import "pyodide"` cannot work from a harness that lives inside an installed Python
package: ESM resolves relative to the importing file, and there is no `node_modules` above
`site-packages`. The harnesses therefore resolve packages from a directory this module
finds, by walking up from the user's working directory the same way Node itself would.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import shutil
import subprocess  # textual-wasm: allow subprocess.run - drives node, native-only
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_log: Final = logging.getLogger(__name__)

HARNESS_DIR: Final[Path] = Path(__file__).parent / "harness"
"""The `.mjs` harnesses, shipped with the package so a user needs no checkout."""

PYODIDE_PACKAGE: Final[str] = "pyodide"
PUPPETEER_PACKAGE: Final[str] = "puppeteer-core"

INSTALL_HINT: Final[str] = "install them where you run this: `pnpm add -D {packages}`"

DEFAULT_TIMEOUT: Final[float] = 600.0
"""A cold Pyodide boot plus a dependency install is a minute; a browser leg is more."""


class HarnessError(RuntimeError):
    """Raised when a harness ran but produced nothing a caller can use."""


@dataclasses.dataclass(frozen=True, slots=True)
class NodeAvailability:
    """Whether a JavaScript leg can run here, and what to do if not."""

    node: str | None
    resolve_from: Path | None
    """Directory containing the `node_modules` the harness will resolve against."""

    missing: tuple[str, ...]
    """Packages that were looked for and not found."""

    @property
    def available(self) -> bool:
        return self.node is not None and self.resolve_from is not None and not self.missing

    @property
    def reason(self) -> str:
        """Why this leg cannot run, phrased as the thing to do about it."""
        if self.node is None:
            return "node is not on PATH; install Node to run the browser and Pyodide legs"
        if self.missing:
            return f"{', '.join(self.missing)} not found - " + INSTALL_HINT.format(
                packages=" ".join(self.missing)
            )
        return "available"


def _package_root(package: str, start: Path) -> Path | None:
    """The nearest ancestor of `start` whose `node_modules` holds `package`."""
    for directory in (start, *start.parents):
        if (directory / "node_modules" / package / "package.json").is_file():
            return directory
    return None


def availability(packages: Sequence[str], *, start: Path | None = None) -> NodeAvailability:
    """Report whether `packages` can be loaded by a harness launched from `start`.

    Args:
        packages: npm package names the harness will require.
        start: Directory to search upward from. Defaults to the working directory, because
            that is where a user's own `node_modules` is.

    Returns:
        What was found, and the instruction for what was not.
    """
    root = start or Path.cwd()
    roots = {package: _package_root(package, root) for package in packages}
    found = [directory for directory in roots.values() if directory is not None]
    return NodeAvailability(
        node=shutil.which("node"),
        resolve_from=found[0] if found else None,
        missing=tuple(name for name, directory in roots.items() if directory is None),
    )


@dataclasses.dataclass(frozen=True, slots=True)
class HarnessResult:
    """What a harness produced."""

    returncode: int
    payload: dict[str, object]
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run_harness(
    script: str,
    config: Mapping[str, object],
    *,
    node: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> HarnessResult:
    """Run one packaged harness and parse the JSON it writes to stdout.

    Args:
        script: File name inside the harness directory.
        config: Everything the run needs, written to a temporary file the harness reads.
        node: The Node binary, from :func:`availability`.
        timeout: Seconds before the harness is abandoned.

    Returns:
        The parsed payload, the exit status, and whatever the harness said on stderr - which
        is where a browser's console errors and Pyodide's own chatter go.

    Raises:
        HarnessError: If the harness wrote something other than a JSON object, which means
            it failed in a way it did not report; its stderr is attached, because on its own
            "expecting value: line 1 column 1" names nothing anyone can act on.
    """
    harness = HARNESS_DIR / script
    with tempfile.TemporaryDirectory(prefix="textual-wasm-") as directory:
        config_path = Path(directory) / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        _log.debug("running %s with %s", harness, dict(config))
        completed = subprocess.run(  # noqa: S603 - argv is ours, no shell
            [node, str(harness), str(config_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    try:
        decoded: object = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise HarnessError(
            f"{script} produced no JSON (exit {completed.returncode}); "
            f"stderr:\n{completed.stderr.strip()}"
        ) from error
    if not isinstance(decoded, dict):
        raise HarnessError(f"{script} produced {type(decoded).__name__}, expected an object")
    return HarnessResult(
        returncode=completed.returncode,
        payload=cast("dict[str, object]", decoded),
        stderr=completed.stderr,
    )
