import subprocess
from pathlib import Path


def test_mojo_fr_smoke() -> None:
    repo = Path(__file__).resolve().parents[1]
    bin_path = repo / "pardal_router_mojo" / "build" / "pardal-router-mojo"
    if not bin_path.exists():
        build = repo / "pardal_router_mojo" / "build.sh"
        subprocess.run([str(build)], cwd=str(build.parent), check=True)
    subprocess.run([str(bin_path), "fr-smoke"], cwd=str(repo), check=True)

