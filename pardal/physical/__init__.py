"""Text-defined physical design compiler surface."""

from pardal.physical.compiler import (
    CompilePhysicalResult,
    ProductionCheckEntry,
    check_production_readiness,
    format_drc_violations,
    format_drc_violations_json,
    format_production_checks,
    format_production_checks_json,
    summarize_drc_unconnected,
    compile_physical,
)
from pardal.physical.spec import PhysicalSpec, load_physical_spec

__all__ = [
    "CompilePhysicalResult",
    "PhysicalSpec",
    "ProductionCheckEntry",
    "check_production_readiness",
    "format_drc_violations",
    "format_drc_violations_json",
    "format_production_checks",
    "format_production_checks_json",
    "compile_physical",
    "load_physical_spec",
    "summarize_drc_unconnected",
]
