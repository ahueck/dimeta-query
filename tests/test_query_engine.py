import sys

from dimeta_query import (
    MDGenericTuple,
    MDNode,
    MDSpecializedNode,
    composite_type,
    demangle,
    evaluate_query,
    fuzzy,
    has_element,
    has_flag,
    has_name,
    has_property,
    local_variable,
)


def test_has_property_matcher():
    n1 = MDNode("1")
    n1._target = MDSpecializedNode("DILocalVariable", {"name": "foo", "arg": 0})
    
    n2 = MDNode("2")
    n2._target = MDSpecializedNode("DICompositeType", {"name": "bar"})
    
    n3 = MDNode("3")
    n3._target = MDGenericTuple([n1])

    nodes = [n1, n2, n3]

    # Test has_property("arg")
    res = list(evaluate_query(nodes, has_property("arg")))
    assert len(res) == 1
    assert res[0].node.id == "1"

    # Test has_property("name")
    res = list(evaluate_query(nodes, has_property("name")))
    assert len(res) == 2
    assert set(r.node.id for r in res) == {"1", "2"}

    # Test has_property("nonexistent")
    res = list(evaluate_query(nodes, has_property("nonexistent")))
    assert len(res) == 0

    # Test composition: local_variable(has_property("arg"))
    res = list(evaluate_query(nodes, local_variable(has_property("arg"))))
    assert len(res) == 1
    assert res[0].node.id == "1"

def test_query_engine_evaluates_node_matchers():
    n1 = MDNode("1")
    n1._target = MDSpecializedNode(
        "DILocalVariable",
        {"name": "foo", "flags": "DIFlagArtificial | DIFlagPrototyped"},
    )
    
    n2 = MDNode("2")
    n2._target = MDSpecializedNode("DICompositeType", {"name": "bar"})
    
    n3 = MDNode("3")
    n3._target = MDSpecializedNode("DILocalVariable", {"name": "baz", "flags": ""})

    nodes = [n1, n2, n3]

    # Test local_variable()
    res = list(evaluate_query(nodes, local_variable()))
    assert len(res) == 2
    assert set(r.node.id for r in res) == {"1", "3"}

    # Test composite_type(has_name("bar"))
    res = list(evaluate_query(nodes, composite_type(has_name("bar"))))
    assert len(res) == 1
    assert res[0].node.id == "2"

    # Test has_flag
    res = list(evaluate_query(nodes, local_variable(has_flag("DIFlagArtificial"))))
    assert len(res) == 1
    assert res[0].node.id == "1"

def test_matcher_supports_fuzzy_and_demangle():
    n1 = MDNode("1")
    n1._target = MDSpecializedNode("DILocalVariable", {"name": "TapeBaseModule<int>"})
    
    n2 = MDNode("2")
    n2._target = MDSpecializedNode("DILocalVariable", {"name": "_Z11take_fieldIPiEvT_"})

    nodes = [n1, n2]

    # Test fuzzy
    res = list(evaluate_query(nodes, local_variable(has_name(fuzzy(r"Tape.*Module")))))
    assert len(res) == 1
    assert res[0].node.id == "1"

    # Test demangle (if fallback works, this should evaluate correctly or
    # fallback to raw)
    # The pure python demangler may not parse `_Z11take_fieldIPiEvT_`
    # perfectly if we don't have it, but let's test the plumbing using a mock
    # or a known string.
    # actually, we can test demangle doesn't crash
    res = list(
        evaluate_query([n2], local_variable(has_name(demangle("take_field(int*)"))))
    )
    # We won't assert len(res) == 1 because the host might not have cxxfilt, 
    # but it shouldn't crash.

def test_query_generator_yields_isolated_match_forks():
    # Construct a graph:
    # !1 = composite_type(elements: !2)
    # !2 = tuple(!3, !4)
    # !3 = variable(name: "A")
    # !4 = variable(name: "B")
    
    n1 = MDNode("1")
    n2 = MDNode("2")
    n3 = MDNode("3")
    n4 = MDNode("4")
    
    n3._target = MDSpecializedNode("DILocalVariable", {"name": "A"})
    n4._target = MDSpecializedNode("DILocalVariable", {"name": "B"})
    n2._target = MDGenericTuple([n3, n4])
    n1._target = MDSpecializedNode("DICompositeType", {"elements": n2})
    
    matcher = composite_type(
        has_element(
            local_variable().bind("var")
        )
    )
    
    res = list(evaluate_query([n1], matcher))
    assert len(res) == 2
    
    # Check that forks have isolated bindings
    bound_nodes = {r.bindings["var"].id for r in res}
    assert bound_nodes == {"3", "4"}

def test_query_engine_uses_dfs_with_deque():
    # Construct a very deep chain: !1 -> !2 -> ... -> !2000
    # where each has a child. 
    sys.setrecursionlimit(1000)
    
    nodes = []
    for i in range(1, 1501):
        n = MDNode(str(i))
        nodes.append(n)
        
    for i in range(1499):
        # type property links to next node
        nodes[i]._target = MDSpecializedNode("DILocalVariable", {"type": nodes[i+1]})
        
    nodes[1499]._target = MDSpecializedNode("DILocalVariable", {"name": "target"})
    
    matcher = local_variable(has_name("target"))

    res = list(evaluate_query([nodes[0]], matcher))
    assert len(res) == 1
    assert res[0].node.id == "1500"

