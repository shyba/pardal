"""Tests for message formatting module."""

import pytest
from pcb_tool.messages import success, error


def test_success_message_format():
    """Test success message formatting."""
    result = success("Component moved")
    assert result == "OK: Component moved"


def test_success_message_empty():
    """Test success with empty message."""
    result = success("")
    assert result == "OK: "


def test_error_message_format():
    """Test error message formatting."""
    result = error("Component not found")
    assert result == "ERROR: Component not found"


def test_error_message_empty():
    """Test error with empty message."""
    result = error("")
    assert result == "ERROR: "


def test_messages_consistent_prefix():
    """Verify prefixes are consistent."""
    assert success("test").startswith("OK: ")
    assert error("test").startswith("ERROR: ")
