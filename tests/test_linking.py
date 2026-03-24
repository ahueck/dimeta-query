from dimeta_query.model import MDGenericTuple, MDNode, MDSpecializedNode
from dimeta_query.parser import parse_metadata, validate_graph


def test_single_pass_linking():
    node_map = {}
    
    # 1. Define a node that references a future node (!2)
    line1 = '!1 = !{!2}'
    node1 = parse_metadata(line1, node_map)
    
    assert isinstance(node1, MDNode)
    assert node1.id == '1'
    assert isinstance(node1._target, MDGenericTuple)
    
    # Check that !2 exists as a proxy
    assert '2' in node_map
    node2_proxy = node_map['2']
    assert isinstance(node2_proxy, MDNode)
    assert node2_proxy._target is None
    
    # Verify the link
    assert node1._target.elements[0] is node2_proxy
    
    # 2. Define the referenced node (!2)
    line2 = '!2 = !{!"leaf"}'
    node2_resolved = parse_metadata(line2, node_map)
    
    # Assert that the object identity is preserved
    assert node2_resolved is node2_proxy
    assert node2_proxy._target is not None
    assert isinstance(node2_proxy._target, MDGenericTuple)
    assert node2_proxy._target.elements[0] == "leaf"

def test_cycle_handling():
    node_map = {}
    
    # !1 = !{!1}
    line = '!1 = !{!1}'
    node1 = parse_metadata(line, node_map)
    
    assert node1.id == '1'
    assert node1._target.elements[0] is node1

def test_specialized_node_parsing():
    node_map = {}
    line = '!1 = !DICompileUnit(language: DW_LANG_C99, file: !2)'
    node1 = parse_metadata(line, node_map)
    
    assert isinstance(node1._target, MDSpecializedNode)
    assert node1._target.dwarf_tag == 'DICompileUnit'
    
    props = node1._target.properties
    assert props['language'] == 'DW_LANG_C99'
    assert props['file'] is node_map['2']

def test_unresolved_proxy_detection():
    node_map = {}
    parse_metadata('!1 = !{!2}', node_map)
    
    unresolved = validate_graph(node_map)
    assert '2' in unresolved
    assert '1' not in unresolved
    
    parse_metadata('!2 = !{}', node_map)
    unresolved = validate_graph(node_map)
    assert len(unresolved) == 0

def test_multiple_lines_consistency():
    node_map = {}
    lines = [
        '!1 = !{!2}',
        '!2 = !{!3}',
        '!3 = !{!"end"}'
    ]
    
    for line in lines:
        parse_metadata(line, node_map)
        
    assert len(validate_graph(node_map)) == 0
    
    n1 = node_map['1']
    n2 = node_map['2']
    n3 = node_map['3']
    
    assert n1._target.elements[0] is n2
    assert n2._target.elements[0] is n3
    assert n3._target.elements[0] == "end"
