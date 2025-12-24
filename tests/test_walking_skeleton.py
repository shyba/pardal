# tests/test_walking_skeleton.py
import subprocess
import sys
from pathlib import Path

def test_cli_help():
    """Test that --help flag works and shows basic usage"""
    result = subprocess.run(
        [sys.executable, "-m", "pcb_tool", "--help"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent
    )
    assert result.returncode == 0, f"CLI failed with: {result.stderr}"
    assert "PCB Place & Route Tool" in result.stdout
    assert "usage:" in result.stdout.lower() or "Usage:" in result.stdout

def test_cli_version():
    """Test that --version flag works and shows version"""
    result = subprocess.run(
        [sys.executable, "-m", "pcb_tool", "--version"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent
    )
    assert result.returncode == 0, f"CLI failed with: {result.stderr}"
    assert "0.1.0" in result.stdout
    assert "MVP1" in result.stdout

def test_cli_runs_without_args():
    """Test that CLI can be invoked without crashing"""
    result = subprocess.run(
        [sys.executable, "-m", "pcb_tool"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent
    )
    # Should either show help or enter interactive mode gracefully
    assert result.returncode in [0, 1], f"CLI crashed with: {result.stderr}"
