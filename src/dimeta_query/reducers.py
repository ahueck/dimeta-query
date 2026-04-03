import os
from typing import Dict, List

from .model import MDNode, MDSpecializedNode


def get_full_path(node: MDNode) -> str:
    """Combines directory and filename from a DIFile node."""
    if not node._target or not isinstance(node._target, MDSpecializedNode):
        return ""
    
    props = node._target.properties
    filename = props.get("filename", "")
    directory = props.get("directory", "")
    
    if not directory or os.path.isabs(filename):
        return str(filename)
    return str(os.path.join(directory, filename))


def calculate_shortest_unique_suffixes(paths: List[str]) -> Dict[str, str]:
    """
    Computes the shortest unique suffix for each path in the provided list.
    """
    if not paths:
        return {}

    # Normalize paths and identify unique ones
    normalized_paths = [os.path.normpath(p) for p in paths]
    unique_paths = sorted(list(set(normalized_paths)))
    
    path_to_suffix = {}
    
    for path in unique_paths:
        parts = path.split(os.sep)
        # Handle cases where path starts with / (root)
        if path.startswith(os.sep):
            parts[0] = os.sep
            
        found = False
        for i in range(1, len(parts) + 1):
            suffix = os.path.join(*parts[-i:])
            
            # Check if this suffix is a suffix of any OTHER path
            is_unique = True
            for other_path in unique_paths:
                if other_path == path:
                    continue
                
                # A suffix is NOT unique if:
                # 1. Other path ends with /suffix
                # 2. Other path IS the suffix
                if other_path.endswith(os.sep + suffix) or other_path == suffix:
                    is_unique = False
                    break
            
            if is_unique:
                path_to_suffix[path] = suffix
                found = True
                break
        
        if not found:
            # Fallback to full path if no unique suffix is found
            path_to_suffix[path] = path

    return {p: path_to_suffix[os.path.normpath(p)] for p in paths}


def regenerate_difile_text(node: MDNode) -> str:
    """
    Regenerates the raw_text for a DIFile node based on its current properties.
    Format: !ID = [distinct] !DIFile(filename: "...", directory: "...")
    """
    if not node._target or not isinstance(node._target, MDSpecializedNode):
        return node.raw_text

    props = node._target.properties
    
    parts = []
    if "filename" in props:
        parts.append(f'filename: "{props["filename"]}"')
    if "directory" in props:
        parts.append(f'directory: "{props["directory"]}"')
        
    payload = f"!DIFile({', '.join(parts)})"
    prefix = f"!{node.id} = "
    if node.is_distinct:
        prefix += "distinct "
        
    return f"{prefix}{payload}"


def reduce_difile_nodes(node_map: Dict[str, MDNode]) -> int:
    """
    Reduces DIFile nodes by shortening filename and directory paths independently
    and removing checksums.
    Returns the number of nodes modified.
    """
    difile_nodes: List[MDNode] = []
    filenames: List[str] = []
    directories: List[str] = []
    
    for node in node_map.values():
        if (node._target and 
            isinstance(node._target, MDSpecializedNode) and 
            node._target.dwarf_tag == "DIFile"):
            difile_nodes.append(node)
            props = node._target.properties
            filenames.append(props.get("filename", ""))
            directories.append(props.get("directory", ""))
            
    if not difile_nodes:
        return 0
    
    filename_to_short = calculate_shortest_unique_suffixes(filenames)
    directory_to_short = calculate_shortest_unique_suffixes(directories)
    
    modified_count = 0
    for node, filename, directory in zip(difile_nodes, filenames, directories):
        target = node._target
        assert isinstance(target, MDSpecializedNode)
        
        if filename:
            target.properties["filename"] = filename_to_short[filename]
        if directory:
            target.properties["directory"] = directory_to_short[directory]
        
        target.properties.pop("checksum", None)
        target.properties.pop("checksumkind", None)
        
        node.raw_text = regenerate_difile_text(node)
        modified_count += 1
        
    return modified_count
