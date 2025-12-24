"""
NetlistReader for KiCad Netlist Files

Parses KiCad S-expression format netlist files (.net) and populates Board objects.
"""

import re
from pathlib import Path
from typing import Optional

from pcb_tool.data_model import Board, Component, Net
from pcb_tool.footprint_library import get_footprint_pads


class NetlistReader:
    """Reader for KiCad netlist files in S-expression format."""

    def read(self, path: Path) -> Board:
        """Read and parse a KiCad netlist file.

        Args:
            path: Path to the .net netlist file

        Returns:
            Board object populated with components and nets

        Raises:
            FileNotFoundError: If the file doesn't exist
            PermissionError: If the file cannot be read due to permissions
            IOError: If there's an error reading the file
        """
        if not path.exists():
            raise FileNotFoundError(f"Netlist file not found: {path}")

        try:
            content = path.read_text()
        except PermissionError as e:
            raise PermissionError(f"Permission denied reading {path}: {e}")
        except IOError as e:
            raise IOError(f"Error reading {path}: {e}")
        except Exception as e:
            raise IOError(f"Unexpected error reading {path}: {e}")

        board = Board(source_file=path)

        # Parse components
        components_section = self._extract_section(content, "components")
        if components_section:
            comp_blocks = self._extract_blocks(components_section, "comp")
            for comp_block in comp_blocks:
                component = self._parse_component(comp_block)
                if component:
                    board.add_component(component)

        # Parse nets
        nets_section = self._extract_section(content, "nets")
        if nets_section:
            net_blocks = self._extract_blocks(nets_section, "net")
            for net_block in net_blocks:
                net = self._parse_net(net_block)
                if net:
                    board.add_net(net)

        return board

    def _extract_section(self, content: str, section_name: str) -> Optional[str]:
        """Extract a top-level section from the netlist.

        Args:
            content: Full netlist content
            section_name: Name of section to extract (e.g., "components", "nets")

        Returns:
            Section content or None if not found
        """
        # Find section start
        pattern = f'({section_name}'
        start_idx = content.find(pattern)
        if start_idx == -1:
            return None

        # Balance parentheses to find section end
        depth = 0
        i = start_idx
        while i < len(content):
            if content[i] == '(':
                depth += 1
            elif content[i] == ')':
                depth -= 1
                if depth == 0:
                    # Found matching close paren
                    section = content[start_idx:i+1]
                    # Extract inner content (remove outer parens and section name)
                    inner = section[len(f'({section_name}'):-1].strip()
                    return inner if inner else ""
            i += 1
        return None

    def _extract_blocks(self, section: str, block_type: str) -> list[str]:
        """Extract all blocks of a specific type from a section.

        Args:
            section: Section content
            block_type: Type of block to extract (e.g., "comp", "net")

        Returns:
            List of block contents
        """
        if not section:
            return []

        blocks = []
        depth = 0
        start_idx = None
        i = 0

        while i < len(section):
            # Look for block start
            if section[i] == '(' and start_idx is None:
                # Check if this is the start of our block type
                remaining = section[i:]
                if remaining.startswith(f"({block_type} ") or remaining.startswith(f"({block_type}\n"):
                    start_idx = i
                    depth = 1
                    i += 1
                    continue

            if start_idx is not None:
                if section[i] == '(':
                    depth += 1
                elif section[i] == ')':
                    depth -= 1
                    if depth == 0:
                        # Found complete block
                        blocks.append(section[start_idx:i+1])
                        start_idx = None

            i += 1

        return blocks

    def _parse_component(self, comp_block: str) -> Optional[Component]:
        """Parse a component block.

        Args:
            comp_block: Component S-expression block

        Returns:
            Component object or None if parsing fails
        """
        ref = self._extract_field(comp_block, "ref")
        value = self._extract_field(comp_block, "value")
        footprint = self._extract_field(comp_block, "footprint")

        if ref and value and footprint:
            # Get pad definitions for this footprint
            pads = get_footprint_pads(footprint)

            return Component(
                ref=ref,
                value=value,
                footprint=footprint,
                position=(0.0, 0.0),  # Default position
                rotation=0.0,          # Default rotation
                locked=False,          # Default unlocked
                pads=pads              # Populate pads from footprint library
            )
        return None

    def _parse_net(self, net_block: str) -> Optional[Net]:
        """Parse a net block.

        Args:
            net_block: Net S-expression block

        Returns:
            Net object or None if parsing fails
        """
        code = self._extract_field(net_block, "code")
        name = self._extract_field(net_block, "name")

        if code is not None and name is not None:
            net = Net(name=name, code=code)

            # Extract all node connections
            # Use [^)] to match everything except closing paren
            node_pattern = r'\(node\s+\(ref\s+([^)]+)\)\s+\(pin\s+([^)]+)\)\)'
            nodes = re.findall(node_pattern, net_block)
            for ref, pin in nodes:
                net.add_connection(ref, pin)

            return net
        return None

    def _extract_field(self, block: str, field_name: str) -> Optional[str]:
        """Extract a field value from an S-expression block.

        Args:
            block: S-expression block
            field_name: Name of field to extract

        Returns:
            Field value or None if not found
        """
        # Pattern to match (field_name value) where value might be quoted or unquoted
        pattern = rf'\({field_name}\s+([^)]+)\)'
        match = re.search(pattern, block)
        if match:
            value = match.group(1).strip()
            # Remove quotes if present
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            return value
        return None
