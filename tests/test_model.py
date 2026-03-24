import pytest

from dimeta_query.model import (
    MDGenericTuple,
    MDNode,
    MDSpecializedNode,
    UnresolvedProxyError,
)
from dimeta_query.parser import parse_metadata


def test_node_slots_enforcement():
    node = MDNode("0")
    with pytest.raises(AttributeError):
        node.arbitrary_attr = "fail"

def test_specialized_node_slots_enforcement():
    node = MDSpecializedNode("DILocation", {})
    with pytest.raises(AttributeError):
        node.arbitrary_attr = "fail"

def test_generic_tuple_slots_enforcement():
    node = MDGenericTuple([])
    with pytest.raises(AttributeError):
        node.arbitrary_attr = "fail"

def test_unresolved_proxy_raises_error():
    node = MDNode("0")
    with pytest.raises(UnresolvedProxyError):
        node.children()

def test_generic_tuple_children():
    node2 = MDNode("2")
    node2._target = MDGenericTuple([])
    
    node1 = MDNode("1")
    node1._target = MDGenericTuple([node2, "not a node"])
    
    children = node1.children()
    assert len(children) == 1
    assert children[0] is node2

def test_specialized_node_children():
    node2 = MDNode("2")
    node2._target = MDGenericTuple([])
    
    node1 = MDNode("1")
    specialized = MDSpecializedNode("DICompileUnit", {})
    specialized._parsed_properties = {"file": node2, "other": "string"}
    node1._target = specialized
    
    children = node1.children()
    assert len(children) == 1
    assert children[0] is node2

def test_specialized_node_eager_parsing():
    node_map = {}
    line = '!1 = !DICompileUnit(language: DW_LANG_C99, file: !2)'
    node = parse_metadata(line, node_map)
    
    target = node._target
    assert isinstance(target, MDSpecializedNode)
    
    # Access properties
    props = target.properties
    
    # Verify parsing occurred eagerly
    assert target._parsed_properties is not None
    assert props['language'] == 'DW_LANG_C99'
    assert props['file'] is node_map['2']
    assert node_map['2'].ref_count == 1

def test_node_distinct_qualifier():
    node_map = {}
    
    # Test distinct
    line_distinct = '!1 = distinct !{!"distinct_node"}'
    node_distinct = parse_metadata(line_distinct, node_map)
    assert node_distinct.id == '1'
    assert node_distinct.is_distinct is True
    
    # Test not distinct
    line_normal = '!2 = !{!"normal_node"}'
    node_normal = parse_metadata(line_normal, node_map)
    assert node_normal.id == '2'
    assert node_normal.is_distinct is False

def test_node_raw_text_preservation():
    node_map = {}
    
    line = '!1 = !{!"some_data"}'
    node = parse_metadata(line, node_map)
    assert node.raw_text == line

    line_distinct = '!2 = distinct !DICompileUnit(language: 12)'
    node_distinct = parse_metadata(line_distinct, node_map)
    assert node_distinct.raw_text == line_distinct

def test_specialized_node_property_parsing():
    node_map = {}
    
    line = '!1 = !DICompileUnit(language: 12, file: !2)'
    node = parse_metadata(line, node_map)
    
    target = node._target
    assert isinstance(target, MDSpecializedNode)
    
    # Check parsed properties
    assert target.properties == {"language": 12, "file": node_map["2"]}

    # Test nested parens if possible, or just simpler case
    line2 = '!2 = !DIBasicType(name: "int")'
    node2 = parse_metadata(line2, node_map)
    target2 = node2._target
    assert isinstance(target2, MDSpecializedNode)
    assert target2.properties == {"name": "int"}

    # Test empty payload
    line3 = '!3 = !DIEof()'
    node3 = parse_metadata(line3, node_map)
    target3 = node3._target
    assert isinstance(target3, MDSpecializedNode)
    assert target3.properties == {}
