import os
import re
from collections import defaultdict
from typing import Dict, List, Tuple

from .model import MDNode
from .parser import MetadataParseError, parse_metadata, validate_graph
from .unparser import Unparser

# 1. Matches ANY attachment pattern: "!name !id"
ATTACHMENT_RE = re.compile(r'!(\w+)\s+!(\d+)')
# 2. Matches debug records to isolate their arguments
#    (Greedy to handle nested parens in !DIExpression)
DBG_RECORD_RE = re.compile(r'#dbg_(\w+)\s*\((.*)\)')
# 3. Matches llvm.dbg.* intrinsics to isolate their arguments
DBG_INTRINSIC_RE = re.compile(r'call\s+.*?(?:@llvm\.dbg\.(\w+))\s*\((.*)\)')
# 4. Extracts individual !<id> references from within isolated argument strings
BANG_ID_RE = re.compile(r'!(\d+)')

def extract_ir_references(ir_lines: List[str]) -> Dict[str, List[Tuple[str, int]]]:
    """
    Scans raw IR lines and builds a context-aware map of metadata references.

    Returns:
        A dictionary mapping `node_id` (str) -> List of (kind, line_idx)
    """
    ir_refs = defaultdict(list)

    for line_idx, line in enumerate(ir_lines):
        # Prevent duplicate (kind, node_id) pairs on the same line
        found_refs = defaultdict(set)

        # Phase 1: Standard trailing attachments
        for match in ATTACHMENT_RE.finditer(line):
            kind = match.group(1)      # e.g., 'dbg', 'tbaa', 'DIAssignID'
            node_id = match.group(2)   # e.g., '165'
            found_refs[node_id].add(kind)

        # Phase 2: Extract arguments from #dbg_ records
        for dbg_match in DBG_RECORD_RE.finditer(line):
            kind = f"dbg_{dbg_match.group(1)}"  # e.g., 'dbg_value', 'dbg_assign'
            args_string = dbg_match.group(2)

            for arg_match in BANG_ID_RE.finditer(args_string):
                node_id = arg_match.group(1)
                found_refs[node_id].add(kind)

        # Phase 3: Extract arguments from @llvm.dbg.* intrinsics
        for intrinsic_match in DBG_INTRINSIC_RE.finditer(line):
            kind = f"dbg_{intrinsic_match.group(1)}"  # e.g., 'dbg_declare'
            args_string = intrinsic_match.group(2)

            for arg_match in BANG_ID_RE.finditer(args_string):
                node_id = arg_match.group(1)
                found_refs[node_id].add(kind)

        for node_id, kinds in found_refs.items():
            for kind in kinds:
                ir_refs[node_id].append((kind, line_idx))

    return dict(ir_refs)

class IRManager:
    """
    Manages the state of an LLVM IR file, including its IR lines and 
    the parsed metadata graph.
    """
    def __init__(self) -> None:
        self.node_map: Dict[str, MDNode] = {}
        self.ir_lines: List[str] = []
        self.ir_refs: Dict[str, List[Tuple[str, int]]] = {}
        self.metadata_count: int = 0
        self.unresolved: List[str] = []

    def parse_file(self, filepath: str) -> None:
        """
        Parses the given .ll file, separating IR from metadata.
        Populates node_map, ir_lines, and ir_refs.
        """
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"File '{filepath}' not found.")

        self.node_map = {}
        self.ir_lines = []
        self.metadata_count = 0

        try:
            with open(filepath, "r") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("!") and "=" in stripped:
                        try:
                            parse_metadata(stripped, self.node_map)
                            self.metadata_count += 1
                        except MetadataParseError as e:
                            print(
                                f"Warning: Failed to parse line: {stripped}"
                                f"\nReason: {e}"
                            )
                    else:
                        self.ir_lines.append(line)
        except Exception as e:
            raise RuntimeError(f"Failed to read file: {e}") from e

        # Post-parse: extract references from IR lines and validate graph
        self.ir_refs = extract_ir_references(self.ir_lines)
        self.unresolved = validate_graph(self.node_map)

    def save_file(self, filepath: str) -> None:
        """
        Validates the current graph and writes the IR and metadata nodes back to a file.
        """
        unparser = Unparser()
        unparser.validate(self.node_map)

        try:
            with open(filepath, "w") as f:
                for ir_line in self.ir_lines:
                    f.write(ir_line)

                # Write metadata definitions sorted by ID
                # Numeric IDs (group 1) after named/string IDs (group 0)
                def _sort_key(x: str) -> Tuple[int, object]:
                    if x.isdigit():
                        return (1, int(x))
                    return (0, x)

                sorted_ids = sorted(self.node_map.keys(), key=_sort_key)
                for node_id in sorted_ids:
                    node_obj = self.node_map[node_id]
                    if node_obj.raw_text:
                        f.write(f"{node_obj.raw_text}\n")
        except Exception as e:
            raise RuntimeError(f"Failed to write file: {e}") from e

    def find_unreferenced_metadata_ids(self, discard_named: bool = False) -> List[str]:
        """
        Identifies metadata IDs that are not reachable from any IR statement
        or any named metadata definition (e.g., !llvm.module.flags) when discard_named=False.
        By default, all named nodes are treated as roots.
        If discard_named is True, named nodes are not automatically treated as roots.
        """
        # 1. Collect roots: IR references AND all named metadata definitions
        roots = set(self.ir_refs.keys())
        if not discard_named:
            for node_id in self.node_map:
                if not node_id.isdigit():
                    roots.add(node_id)
        
        # 2. Transitive reachability
        reachable: set[str] = set()
        stack = list(roots)
        
        while stack:
            node_id = stack.pop()
            if node_id in reachable:
                continue
            
            reachable.add(node_id)
            node = self.node_map.get(node_id)
            if node:
                try:
                    for child in node.children():
                        if child.id not in reachable:
                            stack.append(child.id)
                except Exception:
                    # Proxies or unresolved nodes might fail, but we just 
                    # care about what we CAN reach.
                    pass

        # 3. Identify orphans among IDs that have definitions
        unreferenced = []
        for node_id, node in self.node_map.items():
            if node_id not in reachable:
                # If discard_named=True, include all unreached IDs.
                # Else, only include numeric IDs.
                if discard_named or node_id.isdigit():
                    # Only consider it "removable" if it has a definition 
                    # (not just a proxy)
                    if node.raw_text:
                        unreferenced.append(node_id)
        
        # Sort key: named nodes (-1, name) before numeric nodes (1, int)
        def _sweep_sort_key(x: str) -> Tuple[int, object]:
            if x.isdigit():
                return (1, int(x))
            return (-1, x)

        return sorted(unreferenced, key=_sweep_sort_key)

    def sweep_unreferenced_metadata(self, discard_named: bool = False) -> int:
        """
        Removes unreferenced metadata nodes from the graph.
        Returns the number of nodes removed.
        """
        to_remove = self.find_unreferenced_metadata_ids(discard_named=discard_named)
        for node_id in to_remove:
            del self.node_map[node_id]
        
        # Update metadata count and re-validate unresolved proxies
        self.metadata_count = sum(1 for n in self.node_map.values() if n.raw_text)
        self.unresolved = validate_graph(self.node_map)
        
        return len(to_remove)
