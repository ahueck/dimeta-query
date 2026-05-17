from typing import Dict

from .model import MDNode, UnresolvedProxyError


class DanglingReferenceError(Exception):
    """Raised when the graph contains references to dropped nodes."""
    pass

class Unparser:
    def validate(self, node_map: Dict[str, MDNode]) -> None:
        """
        Validates that all children referenced by any node in the map
        are actually present in the map AND have a definition (raw_text).
        """
        for node_id, node in node_map.items():
            if not node.raw_text:
                continue
            try:
                for child in node.children():
                    if child.id not in node_map or not node_map[child.id].raw_text:
                        reason = "dropped" if child.id in node_map else "missing"
                        raise DanglingReferenceError(
                            f"Node !{node_id} contains a dangling reference to "
                            f"{reason} node !{child.id}"
                        )
            except UnresolvedProxyError:
                # If a proxy was never resolved, it doesn't have children
                pass
