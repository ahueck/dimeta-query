import sys
from importlib import resources
from typing import Any, Dict, List, Optional, Tuple

from lark import Lark, Transformer, exceptions, v_args

from .model import MDGenericTuple, MDNode, MDSpecializedNode


class MetadataParseError(Exception):
    """Raised when the input text fails to parse as valid LLVM metadata."""
    pass

class MetadataTransformer(Transformer[Any, Any]):
    def __init__(
        self, source_text: str, node_map: Optional[Dict[str, MDNode]] = None
    ) -> None:
        super().__init__()
        self.source_text = source_text
        self.node_map: Dict[str, MDNode] = node_map if node_map is not None else {}

    def _get_or_create_node(self, node_id: str) -> MDNode:
        if node_id not in self.node_map:
            self.node_map[node_id] = MDNode(node_id)
        return self.node_map[node_id]

    @v_args(inline=True)
    def node_id(self, token: Any) -> MDNode:
        # Strips '!' if it was somehow included, but based on grammar 
        # "!" (INT | IDENTIFIER), the child is just the INT or IDENTIFIER.
        return self._get_or_create_node(str(token))

    def IDENTIFIER(self, token: Any) -> str:
        s = str(token)
        # Intern DWARF tags, DI nodes, and common LLVM types to save memory
        dwarf_prefixes = ('DW_TAG_', 'DW_ATE_', 'DW_OP_', 'DW_LANG_', 'DI')
        is_dwarf = any(s.startswith(p) for p in dwarf_prefixes)
        is_type = (s.startswith('i') and s[1:].isdigit()) or s in (
            'half', 'float', 'double', 'fp128', 'x86_fp80', 'ppc_fp128', 
            'ptr', 'void', 'label', 'metadata'
        )
        if is_dwarf or is_type:
            return sys.intern(s)
        return s

    # Streamlined literals via branch aliases
    def null(self, _: Any) -> None: return None
    def true(self, _: Any) -> bool: return True
    def false(self, _: Any) -> bool: return False
    def operand_list(self, items: Any) -> List[Any]: return list(items)
    def property_list(self, items: Any) -> Dict[str, Any]: return dict(items)

    @v_args(inline=True)
    def property(self, key: Any, value: Any) -> Tuple[str, Any]:
        return (str(key), value)

    @v_args(inline=True)
    def typed_operand(self, type_token: Any, value: Any) -> Any:
        return value

    @v_args(inline=True)
    def int_const(self, token: Any) -> int:
        return int(token)

    @v_args(inline=True)
    def float_const(self, token: Any) -> float:
        return float(token)

    @v_args(inline=True)
    def string_lit(self, *tokens: Any) -> str:
        # Tokens can be (ESCAPED_STRING,) or ("!", ESCAPED_STRING)
        # We only care about the ESCAPED_STRING token.
        s = str(tokens[-1])
        return s[1:-1] if s.startswith('"') and s.endswith('"') else s

    def flags(self, items: Any) -> str:
        # items is a list of IDENTIFIER tokens
        return " | ".join(str(item) for item in items)

    @v_args(inline=True)
    def tuple(self, operands: Any = None) -> MDGenericTuple:
        ops = operands if operands is not None else []
        for op in ops:
            if isinstance(op, MDNode):
                op.ref_count += 1
        return MDGenericTuple(ops)

    @v_args(inline=True, meta=True)
    def specialized_node(
        self, meta: Any, identifier: Any, payload: Any = None
    ) -> MDSpecializedNode:
        if isinstance(payload, dict):
            for val in payload.values():
                if isinstance(val, MDNode):
                    val.ref_count += 1
                elif isinstance(val, list):
                    for item in val:
                        if isinstance(item, MDNode):
                            item.ref_count += 1
        elif isinstance(payload, list):
            for item in payload:
                if isinstance(item, MDNode):
                    item.ref_count += 1

        node = MDSpecializedNode(str(identifier), payload)
        return node

    # Explicit branch handlers for metadata_def aliases
    @v_args(inline=True, meta=True)
    def distinct_def(self, meta: Any, node: MDNode, payload: Any) -> MDNode:
        node._target = payload
        node.is_distinct = True
        node.raw_text = self.source_text[meta.start_pos:meta.end_pos]
        return node

    @v_args(inline=True, meta=True)
    def normal_def(self, meta: Any, node: MDNode, payload: Any) -> MDNode:
        node._target = payload
        node.is_distinct = False
        node.raw_text = self.source_text[meta.start_pos:meta.end_pos]
        return node

_GRAMMAR = resources.files(__package__).joinpath("grammar.lark").read_text()
_PARSER = Lark(
    _GRAMMAR,
    start=["metadata_def", "property_list", "operand_list"],
    parser="lalr",
    propagate_positions=True,
)

def parse_metadata(line: str, node_map: Optional[Dict[str, MDNode]] = None) -> MDNode:
    """
    Parses a single metadata definition line and updates the node_map.
    Returns the resolved MDNode.
    """
    if node_map is None:
        node_map = {}
    try:
        tree = _PARSER.parse(line, start='metadata_def')
        transformer = MetadataTransformer(line, node_map)
        return transformer.transform(tree) # type: ignore
    except exceptions.LarkError as e:
        raise MetadataParseError(f"Failed to parse metadata: {e}") from e

def validate_graph(node_map: Dict[str, MDNode]) -> List[str]:
    """
    Checks for any MDNode instances that were referenced but never defined.
    Returns a list of unresolved node IDs.
    """
    unresolved = []
    for node_id, node in node_map.items():
        if node._target is None:
            unresolved.append(node_id)
    return unresolved
