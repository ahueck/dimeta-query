import gc
import weakref

import pytest

from dimeta_query.graph_manager import drop_node
from dimeta_query.parser import parse_metadata


def test_ref_counting():
    node_map = {}
    parse_metadata("!1 = !{!2}", node_map)
    parse_metadata("!2 = !{}", node_map)

    assert node_map["2"].ref_count == 1
    assert node_map["1"].ref_count == 0

def test_ref_counting_cycle():
    node_map = {}
    parse_metadata("!1 = !{!1}", node_map)
    assert node_map["1"].ref_count == 1

def test_safe_drop():
    node_map = {}
    parse_metadata("!1 = !{!2}", node_map)
    parse_metadata("!2 = !{}", node_map)

    with pytest.raises(ValueError, match="Cannot drop node with active references"):
        drop_node("2", node_map)

    drop_node("1", node_map)
    assert "1" not in node_map

    # Cascade drop should happen because !2's ref count drops to 0
    assert "2" not in node_map

def test_cascading_drop():
    node_map = {}
    # !1 -> !2 -> !3
    parse_metadata("!1 = !{!2}", node_map)
    parse_metadata("!2 = !{!3}", node_map)
    parse_metadata("!3 = !{}", node_map)

    assert node_map["3"].ref_count == 1
    assert node_map["2"].ref_count == 1
    assert node_map["1"].ref_count == 0

    drop_node("1", node_map)
    assert "1" not in node_map
    assert "2" not in node_map
    assert "3" not in node_map

def test_cycle_drop():
    node_map = {}
    # Cycle !1 <-> !2
    parse_metadata("!1 = !{!2}", node_map)
    parse_metadata("!2 = !{!1}", node_map)

    assert node_map["1"].ref_count == 1
    assert node_map["2"].ref_count == 1

    drop_node("1", node_map, force=True)
    assert "1" not in node_map
    assert "2" not in node_map

def test_force_drop_double_decrement():
    node_map = {}
    # !1 -> !2 -> !3
    # !4 -> !2
    parse_metadata("!1 = !{!2}", node_map)
    parse_metadata("!4 = !{!2}", node_map)
    parse_metadata("!2 = !{!3}", node_map)
    parse_metadata("!3 = !{}", node_map)

    assert node_map["2"].ref_count == 2
    assert node_map["3"].ref_count == 1

    # Drop !2 directly
    drop_node("2", node_map, force=True)
    assert "2" in node_map # Stays as proxy because !1 and !4 reference it
    assert node_map["2"]._target is None
    assert "3" not in node_map # Cascade drops !3

    # Drop !1 (parent of dropped !2)
    drop_node("1", node_map)
    assert "1" not in node_map
    assert node_map["2"].ref_count == 1 # Now only !4 references it

def test_force_drop_reverts_to_proxy():
    node_map = {}
    # !1 -> !2 -> !3
    parse_metadata("!1 = !{!2}", node_map)
    parse_metadata("!2 = !{!3}", node_map)
    parse_metadata("!3 = !{}", node_map)

    assert node_map["2"].ref_count == 1
    assert node_map["3"].ref_count == 1

    # Force drop !2.
    # It has ref_count 1, so it should stay in node_map but as a proxy.
    # !3 should be removed because its ref_count goes to 0.
    drop_node("2", node_map, force=True)

    assert "2" in node_map
    assert node_map["2"]._target is None
    assert node_map["2"].raw_text == ""
    assert node_map["2"].ref_count == 1

    assert "3" not in node_map

def test_unresolved_proxy_drop():
    node_map = {}
    # !1 -> !2, but !2 is never defined
    parse_metadata("!1 = !{!2}", node_map)

    # !2 should be an unresolved proxy
    assert node_map["2"]._target is None

    # Dropping !1 should not crash
    drop_node("1", node_map)
    assert "1" not in node_map
    # node 2 is removed because its ref_count goes to 0, which triggers _cascading_drop
    assert "2" not in node_map

def test_nested_inline_tuple_ref_count():
    node_map = {}
    # !1 contains an inline tuple which contains !2
    parse_metadata("!1 = !{!{!2}}", node_map)
    parse_metadata("!2 = !{}", node_map)

    assert node_map["2"].ref_count == 1

    # When !1 is dropped, !2's ref_count should decrement and it should be
    # cascade-dropped
    drop_node("1", node_map)

    assert "1" not in node_map
    assert "2" not in node_map

def test_cascading_drop_reclaims_memory():
    node_map = {}
    parse_metadata("!1 = !{!2}", node_map)
    parse_metadata("!2 = !{!1}", node_map)

    n1_ref = weakref.ref(node_map["1"])
    n2_ref = weakref.ref(node_map["2"])

    drop_node("1", node_map, force=True)

    # Run garbage collection
    gc.collect()

    # Verify that the objects have been deleted
    assert n1_ref() is None
    assert n2_ref() is None

def test_deep_cascading_drop():
    import sys
    # Create a chain deeper than the current recursion limit
    limit = sys.getrecursionlimit()
    depth = limit + 100
    node_map = {}

    for i in range(depth):
        parse_metadata(f"!{i} = !{{!{i+1}}}", node_map)
    parse_metadata(f"!{depth} = !{{}}", node_map)

    # If recursive, this would raise RecursionError
    drop_node("0", node_map)
    assert len(node_map) == 0
