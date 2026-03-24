import collections
from typing import Dict, Set

from .model import MDNode, UnresolvedProxyError


def _cascading_drop(
    start_node: MDNode, node_map: Dict[str, MDNode], visited: Set[str]
) -> None:
    stack = collections.deque([start_node])
    
    while stack:
        node = stack.pop()
        
        if node.id in visited:
            if node.ref_count == 0 and node.id in node_map:
                del node_map[node.id]
            continue
            
        visited.add(node.id)
        
        if node.id not in node_map:
            continue
            
        try:
            # Must get children before target is cleared
            children = node.children()
        except UnresolvedProxyError:
            children = []
            
        if node.ref_count > 0:
            # Still referenced, revert to proxy
            node._target = None
            node.raw_text = ""
            node.is_distinct = False
        else:
            # No references, remove from map
            del node_map[node.id]
            
        for child in children:
            child.ref_count -= 1
            if child.ref_count == 0:
                stack.append(child)

def drop_node(node_id: str, node_map: Dict[str, MDNode], force: bool = False) -> None:
    """
    Drops a node from the graph and cascades the deletion to its children
    if their reference counts drop to zero.
    
    Raises ValueError if the node has active references and force is False.
    """
    if node_id not in node_map:
        return

    node = node_map[node_id]
    if node.ref_count > 0 and not force:
        raise ValueError("Cannot drop node with active references")

    _cascading_drop(node, node_map, set())
