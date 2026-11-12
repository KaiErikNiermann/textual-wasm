"""Where the benchmark's files live, computed once from this file's location."""

from __future__ import annotations

from pathlib import Path
from typing import Final

BENCH: Final[Path] = Path(__file__).resolve().parents[1]
"""The `bench/` directory: the two packages, the harness and the committed results."""

REPOSITORY: Final[Path] = BENCH.parent

HARNESS: Final[Path] = BENCH / "harness"
PAGES: Final[Path] = HARNESS / "pages"
APPS: Final[Path] = BENCH / "bench_apps"
RESULTS: Final[Path] = BENCH / "results"

SCRATCH: Final[Path] = REPOSITORY / ".scratch" / "bench"
"""Built sites and partial runs. Gitignored; nothing here is kept."""

DOCS_TABLES: Final[Path] = REPOSITORY / "docs" / "benchmark-results.md"
"""The rendered tables the benchmarks page includes."""
