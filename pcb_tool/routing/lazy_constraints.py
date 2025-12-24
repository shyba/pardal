"""
Lazy Constraints Module

Manages blocking constraints for Z3 iterative refinement.
Implements lazy constraint addition to prevent detected crossings.
"""

from typing import List, Dict, Tuple


class LazyConstraintManager:
    """Manage blocking constraints for Z3 iterative refinement."""

    def __init__(self):
        """Initialize constraint manager."""
        self.blocked_cells: List[Tuple[str, Tuple[int, int], str]] = []  # (net_name, cell, layer)

    def add_crossing_blocks(self, crossings: List['Crossing']):
        """
        Add constraints to prevent detected crossings.

        Strategy: For each crossing, block the SECOND net (lexicographically)
        from using that cell. This provides deterministic behavior.

        Args:
            crossings: List of Crossing objects from CrossingDetector
        """
        for crossing in crossings:
            # Block one net from cell (choose deterministically using max)
            # This ensures consistent behavior across runs
            blocked_net = max(crossing.net1, crossing.net2)
            self.blocked_cells.append((blocked_net, crossing.cell, crossing.layer))

    def apply_to_solver(
        self,
        solver,  # Z3 Solver or Optimize
        cell_vars: Dict[Tuple[int, int, str], 'ArithRef'],
        net_name_to_idx: Dict[str, int]
    ):
        """
        Add blocking constraints to Z3 solver.

        For each blocked cell, adds constraint: cell_vars[cell] != net_idx
        This prevents the blocked net from occupying that cell.

        Args:
            solver: Z3 Solver or Optimize instance
            cell_vars: Dictionary mapping (x, y, layer) -> Z3 Int variable
            net_name_to_idx: Dictionary mapping net name -> net index
        """
        for net_name, cell, layer in self.blocked_cells:
            x, y = cell
            key = (x, y, layer)

            # Check if this cell and net exist in the problem
            if key in cell_vars and net_name in net_name_to_idx:
                idx = net_name_to_idx[net_name]
                # Add constraint: this cell cannot be occupied by this net
                solver.add(cell_vars[key] != idx)

    def get_count(self) -> int:
        """
        Get the number of blocked cells.

        Returns:
            Number of blocked cell constraints
        """
        return len(self.blocked_cells)
