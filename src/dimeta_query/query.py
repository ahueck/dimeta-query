import collections
from typing import Deque, Dict, Generator, Iterable, Iterator, Optional, Set

from .model import MDNode, UnresolvedProxyError


class MatchResult:
    __slots__ = ('node', 'bindings')
    
    def __init__(self, node: MDNode, bindings: Optional[Dict[str, MDNode]] = None):
        self.node = node
        self.bindings = bindings or {}

    def bind(self, name: str, node: MDNode) -> 'MatchResult':
        new_bindings = self.bindings.copy()
        new_bindings[name] = node
        return MatchResult(self.node, new_bindings)

    def clone(self, new_node: Optional[MDNode] = None) -> 'MatchResult':
        node = new_node if new_node is not None else self.node
        return MatchResult(node, self.bindings.copy())

class BaseMatcher:
    def matches(self, node: MDNode, result: MatchResult) -> Generator[MatchResult, None, None]:  # noqa: E501
        raise NotImplementedError

    def bind(self, name: str) -> 'BindMatcher':
        return BindMatcher(self, name)

class BindMatcher(BaseMatcher):
    def __init__(self, inner: BaseMatcher, name: str):
        self.inner = inner
        self.name = name

    def matches(self, node: MDNode, result: MatchResult) -> Generator[MatchResult, None, None]:  # noqa: E501
        for res in self.inner.matches(node, result):
            yield res.bind(self.name, node)

def evaluate_query(start_nodes: Iterable[MDNode], matcher: BaseMatcher) -> Iterator[MatchResult]:  # noqa: E501
    """
    Evaluates a matcher query using an explicit Stack-Based DFS to avoid RecursionError.
    """
    stack: Deque[MDNode] = collections.deque()
    visited: Set[str] = set()
    
    # Push initial nodes
    for sn in start_nodes:
        if sn.id not in visited:
            stack.append(sn)
            visited.add(sn.id)
            
    while stack:
        current_node = stack.pop()
        
        # Test current node against matcher
        initial_result = MatchResult(current_node)
        for res in matcher.matches(current_node, initial_result):
            yield res
            
        # Add children to stack
        try:
            children = current_node.children()
            for child in children:
                if child.id not in visited:
                    visited.add(child.id)
                    stack.append(child)
        except UnresolvedProxyError:
            pass
