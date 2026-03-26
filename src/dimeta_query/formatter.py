from typing import List, Set, Tuple

from dimeta_query.model import MDNode, MDSpecializedNode
from dimeta_query.query import MatchResult


def _get_edges(node: MDNode) -> List[Tuple[str, MDNode]]:
    edges: List[Tuple[str, MDNode]] = []
    if node._target:
        if isinstance(node._target, MDSpecializedNode):
            for k, v in node._target.properties.items():
                if isinstance(v, MDNode):
                    edges.append((k, v))
                elif isinstance(v, list):
                    for i, item in enumerate(v):
                        if isinstance(item, MDNode):
                            edges.append((f"{k}[{i}]", item))
        elif hasattr(node._target, 'elements'):  # MDGenericTuple
            for i, v in enumerate(node._target.elements):
                if isinstance(v, MDNode):
                    edges.append((f"[{i}]", v))
    return edges

def format_ascii_tree(
    match_result: MatchResult, 
    verbose: bool = False, 
    depth: int = -1, 
    name_only: bool = False
) -> str:
    lines: List[str] = []
    
    def get_node_text(node: MDNode) -> str:
        if not name_only:
            return node.raw_text or f"!{node.id} = <proxy>"
        
        # Simple/Summary mode: "!id = [distinct] !Tag"
        prefix = f"!{node.id} = "
        if node.is_distinct:
            prefix += "distinct "
            
        if node._target is None:
            return f"{prefix}<proxy>"
        
        if isinstance(node._target, MDSpecializedNode):
            return f"{prefix}{node._target.dwarf_tag}"
        elif hasattr(node._target, 'elements'): # MDGenericTuple
            return f"{prefix}!{{" + ("..." if node._target.elements else "") + "}"
        return f"{prefix}<unknown>"

    def walk(node: MDNode, prefix: str, visited: Set[str], current_depth: int) -> None:
        if not prefix: # Root
            lines.append(get_node_text(node))
            if depth >= 0 and current_depth >= depth:
                return
            child_prefix = " "
        else:
            child_prefix = prefix
            
        edges = _get_edges(node)
        new_visited = visited | {node.id}
        
        for i, (edge_name, child) in enumerate(edges):
            is_last_edge = (i == len(edges) - 1)
            edge_prefix_char = "└─ " if is_last_edge else "├─ "
            
            # Label heuristic: keep indices (e.g. elements[0]), hide property names
            if verbose or "[" in edge_name:
                 label = f"{edge_name}: "
            else:
                 label = ""
            
            if child.id in new_visited:
                tag_str = ""
                if child._target and isinstance(child._target, MDSpecializedNode):
                    tag_str = f" = {child._target.dwarf_tag}"
                lines.append(
                    f"{child_prefix}{edge_prefix_char}{label}"
                    f"<cycle to !{child.id}{tag_str}>"
                )
            elif depth < 0 or current_depth + 1 <= depth:
                node_text = get_node_text(child)
                lines.append(f"{child_prefix}{edge_prefix_char}{label}{node_text}")
                
                next_prefix = child_prefix + ("    " if is_last_edge else "│   ")
                walk(child, next_prefix, new_visited, current_depth + 1)

    walk(match_result.node, "", set(), 0)
    return "\n".join(lines)
