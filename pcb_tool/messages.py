"""
PCB Tool Message Formatting

Standardized message formatting for consistent user feedback.
"""


def success(msg: str) -> str:
    """Format a success message.

    Args:
        msg: The success message content

    Returns:
        Formatted success message with "OK: " prefix

    Example:
        >>> success("Component moved")
        'OK: Component moved'
    """
    return f"OK: {msg}"


def error(msg: str) -> str:
    """Format an error message.

    Args:
        msg: The error message content

    Returns:
        Formatted error message with "ERROR: " prefix

    Example:
        >>> error("Component not found")
        'ERROR: Component not found'
    """
    return f"ERROR: {msg}"
