import subprocess
from pathlib import Path


def test_mojo_fr_smoke() -> None:
    repo = Path(__file__).resolve().parents[1]
    bin_path = repo / "routing" / "mojo_router" / "build" / "pardal-router-mojo"
    if not bin_path.exists():
        build = repo / "routing" / "mojo_router" / "build.sh"
        subprocess.run([str(build)], cwd=str(build.parent), check=True)
    subprocess.run([str(bin_path), "fr-smoke"], cwd=str(repo), check=True)

