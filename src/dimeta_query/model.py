from typing import Any, Dict, List, Optional, Union


class UnresolvedProxyError(Exception):
    """Raised when accessing children or properties of an unresolved MDNode."""
    pass

class MDNode:
    """Proxy handle. Safely supports forward references."""
    __slots__ = ('id', 'ref_count', '_target', 'is_distinct', 'raw_text', '__weakref__')
    
    id: str
    ref_count: int
    _target: Optional[Union['MDGenericTuple', 'MDSpecializedNode']]
    is_distinct: bool
    raw_text: str

    def __init__(self, node_id: str):
        self.id = node_id
        self.ref_count = 0
        self._target = None
        self.is_distinct = False
        self.raw_text = ""

    def children(self) -> List['MDNode']:
        if self._target is None:
            raise UnresolvedProxyError(f"Node !{self.id} was never defined.")
        return self._target.children()

    def __repr__(self) -> str:
        status = "resolved" if self._target else "proxy"
        return f"<MDNode !{self.id} ({status})>"

class MDSpecializedNode:
    """Concrete instantiation for DWARF metadata nodes."""
    __slots__ = ('dwarf_tag', '_parsed_properties', '_cached_flags')
    
    dwarf_tag: str
    _parsed_properties: Dict[str, Any]
    _cached_flags: Optional[Any] # frozenset once implemented

    def __init__(
        self,
        dwarf_tag: str,
        parsed_properties: Optional[Union[Dict[str, Any], List[Any]]] = None
    ):
        self.dwarf_tag = dwarf_tag
        if isinstance(parsed_properties, list):
            self._parsed_properties = {'operands': parsed_properties}
        elif isinstance(parsed_properties, dict):
            self._parsed_properties = parsed_properties
        else:
            self._parsed_properties = {}
        self._cached_flags = None

    @property
    def properties(self) -> Dict[str, Any]:
        return self._parsed_properties

    def children(self) -> List[MDNode]:
        children = []
        for val in self._parsed_properties.values():
            if isinstance(val, MDNode):
                children.append(val)
            elif hasattr(val, 'children') and not isinstance(val, MDNode):
                children.extend(val.children())
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, MDNode):
                        children.append(item)
                    elif hasattr(item, 'children') and not isinstance(item, MDNode):
                        children.extend(item.children())
        return children

class MDGenericTuple:
    """Concrete instantiation for metadata tuples."""
    __slots__ = ('elements',)
    elements: List[Optional[Union[MDNode, str, int, float, bool]]]

    def __init__(self, elements: List[Any]):
        self.elements = elements

    def children(self) -> List[MDNode]:
        children = []
        for e in self.elements:
            if isinstance(e, MDNode):
                children.append(e)
            elif hasattr(e, 'children') and not isinstance(e, MDNode):
                children.extend(e.children()) # type: ignore
        return children
