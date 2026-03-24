import sys
from typing import Any, Generator, Sequence

from .model import MDGenericTuple, MDNode, MDSpecializedNode, UnresolvedProxyError
from .modifiers import StringModifier
from .query import BaseMatcher, MatchResult


class NodeMatcher(BaseMatcher):
    def __init__(self, tag_name: str, *inner_matchers: BaseMatcher):
        self.tag_name = tag_name
        self.inner_matchers = inner_matchers

    def matches(self, node: MDNode, result: MatchResult) -> Generator[MatchResult, None, None]:  # noqa: E501
        target = getattr(node, '_target', None) if isinstance(node, MDNode) else None
        target_node = target if target is not None else node

        if not isinstance(target_node, MDSpecializedNode):
            return

        if target_node.dwarf_tag != self.tag_name:
            return

        def evaluate_inner(matchers_left: Sequence[BaseMatcher], current_result: MatchResult) -> Generator[MatchResult, None, None]:  # noqa: E501
            if not matchers_left:
                yield current_result
                return
            
            first_matcher = matchers_left[0]
            for next_res in first_matcher.matches(node, current_result):
                yield from evaluate_inner(matchers_left[1:], next_res)

        yield from evaluate_inner(self.inner_matchers, result)

class AnyNodeMatcher(BaseMatcher):
    def __init__(self, inner_matchers: Sequence[BaseMatcher]):
        self.inner_matchers = inner_matchers

    def matches(self, node: MDNode, result: MatchResult) -> Generator[MatchResult, None, None]:  # noqa: E501
        def evaluate_inner(matchers_left: Sequence[BaseMatcher], current_result: MatchResult) -> Generator[MatchResult, None, None]:  # noqa: E501
            if not matchers_left:
                yield current_result
                return
            
            first_matcher = matchers_left[0]
            for next_res in first_matcher.matches(node, current_result):
                yield from evaluate_inner(matchers_left[1:], next_res)
        yield from evaluate_inner(self.inner_matchers, result)

def node(*inner_matchers: BaseMatcher) -> BaseMatcher:
    return AnyNodeMatcher(inner_matchers)

def local_variable(*inner_matchers: BaseMatcher) -> NodeMatcher:
    return NodeMatcher("DILocalVariable", *inner_matchers)

def composite_type(*inner_matchers: BaseMatcher) -> NodeMatcher:
    return NodeMatcher("DICompositeType", *inner_matchers)

def derived_type(*inner_matchers: BaseMatcher) -> NodeMatcher:
    return NodeMatcher("DIDerivedType", *inner_matchers)

def basic_type(*inner_matchers: BaseMatcher) -> NodeMatcher:
    return NodeMatcher("DIBasicType", *inner_matchers)

def subrange(*inner_matchers: BaseMatcher) -> NodeMatcher:
    return NodeMatcher("DISubrange", *inner_matchers)

def subprogram(*inner_matchers: BaseMatcher) -> NodeMatcher:
    return NodeMatcher("DISubprogram", *inner_matchers)

def file_node(*inner_matchers: BaseMatcher) -> NodeMatcher:
    return NodeMatcher("DIFile", *inner_matchers)

def lexical_block(*inner_matchers: BaseMatcher) -> NodeMatcher:
    return NodeMatcher("DILexicalBlock", *inner_matchers)

class NarrowingMatcher(BaseMatcher):
    def __init__(self, property_name: str, expected_value: Any):
        self.property_name = property_name
        self.expected_value = expected_value

    def matches(self, node: MDNode, result: MatchResult) -> Generator[MatchResult, None, None]:  # noqa: E501
        target = getattr(node, '_target', None) if isinstance(node, MDNode) else None
        target_node = target if target is not None else node

        if not isinstance(target_node, MDSpecializedNode):
            return

        if self.property_name not in target_node.properties:
            return

        actual_val = target_node.properties[self.property_name]
        
        if isinstance(self.expected_value, StringModifier):
            if isinstance(actual_val, str) and self.expected_value.evaluate(actual_val):
                yield result
        else:
            if actual_val == self.expected_value:
                yield result

def has_name(name: Any) -> NarrowingMatcher:
    return NarrowingMatcher("name", name)

def has_tag(tag: Any) -> NarrowingMatcher:
    return NarrowingMatcher("tag", tag)

def has_attr(name: str, value: Any) -> NarrowingMatcher:
    return NarrowingMatcher(name, value)

class HasPropertyMatcher(BaseMatcher):
    def __init__(self, property_name: str):
        self.property_name = property_name

    def matches(self, node: MDNode, result: MatchResult) -> Generator[MatchResult, None, None]:  # noqa: E501
        target = getattr(node, '_target', None) if isinstance(node, MDNode) else None
        target_node = target if target is not None else node

        if not isinstance(target_node, MDSpecializedNode):
            return

        if self.property_name in target_node.properties:
            yield result

def has_property(name: str) -> HasPropertyMatcher:
    return HasPropertyMatcher(name)

class HasFlagMatcher(BaseMatcher):
    def __init__(self, flag: str):
        self.flag = flag

    def matches(self, node: MDNode, result: MatchResult) -> Generator[MatchResult, None, None]:  # noqa: E501
        target = getattr(node, '_target', None) if isinstance(node, MDNode) else None
        target_node = target if target is not None else node

        if not isinstance(target_node, MDSpecializedNode):
            return

        if target_node._cached_flags is None:
            flags_str = target_node.properties.get("flags", "")
            if isinstance(flags_str, str):
                flag_set = (f.strip() for f in flags_str.split("|") if f.strip())
                target_node._cached_flags = frozenset(sys.intern(f) for f in flag_set)
            else:
                target_node._cached_flags = frozenset()

        if self.flag in target_node._cached_flags:
            yield result

def has_flag(flag: str) -> HasFlagMatcher:
    return HasFlagMatcher(flag)

class TraversalMatcher(BaseMatcher):
    def __init__(self, edge_name: str, inner_matcher: BaseMatcher):
        self.edge_name = edge_name
        self.inner_matcher = inner_matcher

    def matches(self, node: MDNode, result: MatchResult) -> Generator[MatchResult, None, None]:  # noqa: E501
        target = getattr(node, '_target', None) if isinstance(node, MDNode) else None
        target_node = target if target is not None else node

        if not isinstance(target_node, MDSpecializedNode):
            return

        if self.edge_name not in target_node.properties:
            return
            
        edge_target = target_node.properties[self.edge_name]
        
        items_to_check = []
        
        # If the property is a direct reference to a node (like a proxy to a tuple)
        # We should unwrap the tuple elements if we are using has_element
        # Let's traverse the direct edge target.
        if isinstance(edge_target, list):
            items_to_check = edge_target
        elif isinstance(edge_target, MDGenericTuple):
            items_to_check = edge_target.elements
        elif isinstance(edge_target, MDNode):
            target_edge_node = getattr(edge_target, '_target', None)
            if isinstance(target_edge_node, MDGenericTuple):
                items_to_check = target_edge_node.elements
            else:
                items_to_check = [edge_target]
        else:
            items_to_check = [edge_target]

        for item in items_to_check:
            if isinstance(item, MDNode):
                # evaluate the inner matcher on the connected node
                for sub_res in self.inner_matcher.matches(item, MatchResult(item)):
                    new_res = result.clone()
                    new_res.bindings.update(sub_res.bindings)
                    yield new_res

def has_type(inner_matcher: BaseMatcher) -> TraversalMatcher:
    return TraversalMatcher("type", inner_matcher)

def has_scope(inner_matcher: BaseMatcher) -> TraversalMatcher:
    return TraversalMatcher("scope", inner_matcher)

def has_element(inner_matcher: BaseMatcher) -> TraversalMatcher:
    return TraversalMatcher("elements", inner_matcher)

def has_base_type(inner_matcher: BaseMatcher) -> TraversalMatcher:
    return TraversalMatcher("baseType", inner_matcher)

class HasChildMatcher(BaseMatcher):
    def __init__(self, inner_matcher: BaseMatcher):
        self.inner_matcher = inner_matcher
        
    def matches(self, node: MDNode, result: MatchResult) -> Generator[MatchResult, None, None]:  # noqa: E501
        try:
            children = node.children()
        except UnresolvedProxyError:
            children = []
            
        for child in children:
            for sub_res in self.inner_matcher.matches(child, MatchResult(child)):
                new_res = result.clone()
                new_res.bindings.update(sub_res.bindings)
                yield new_res

def has_child(inner_matcher: BaseMatcher) -> HasChildMatcher:
    return HasChildMatcher(inner_matcher)
