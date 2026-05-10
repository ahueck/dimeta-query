from dimeta_query.formatter import format_ascii_tree
from dimeta_query.model import MDGenericTuple, MDNode, MDSpecializedNode
from dimeta_query.query import MatchResult


def test_formatter_formats_ascii_tree_with_cycles():
    n1 = MDNode("1")
    n2 = MDNode("2")
    n3 = MDNode("3")

    n1._target = MDSpecializedNode("DW_TAG_1", {"name": "n1", "child": n2})
    n1.raw_text = '!1 = !DW_TAG_1(name: "n1", child: !2)'

    n2._target = MDSpecializedNode("DW_TAG_2", {"name": "n2", "child": n3})
    n2.raw_text = '!2 = !DW_TAG_2(name: "n2", child: !3)'

    # n3 has a cycle back to n1
    n3._target = MDSpecializedNode("DW_TAG_3", {"parent": n1})
    n3.raw_text = '!3 = !DW_TAG_3(parent: !1)'

    match_result = MatchResult(n1)

    output = format_ascii_tree(match_result)

    expected = """!1 = !DW_TAG_1(name: "n1", child: !2)
 └─ !2 = !DW_TAG_2(name: "n2", child: !3)
     └─ !3 = !DW_TAG_3(parent: !1)
         └─ <cycle to !1 = DW_TAG_1>"""

    assert output == expected

def test_formatter_with_list_properties():
    n1 = MDNode("1")
    n2 = MDNode("2")

    n2._target = MDSpecializedNode("DW_TAG_2", {})
    n2.raw_text = '!2 = !DW_TAG_2()'

    n1._target = MDSpecializedNode("DW_TAG_1", {"elements": [n2]})
    n1.raw_text = '!1 = !DW_TAG_1(elements: !{ !2 })'

    match_result = MatchResult(n1)
    output = format_ascii_tree(match_result)

    expected = """!1 = !DW_TAG_1(elements: !{ !2 })
 └─ elements[0]: !2 = !DW_TAG_2()"""

    assert output == expected

def test_formatter_with_generic_tuple():
    n1 = MDNode("1")
    n2 = MDNode("2")

    n2._target = MDGenericTuple([MDNode("3")]) # node 3 is a proxy
    n2.raw_text = '!2 = !{ !3 }'

    n1._target = MDGenericTuple([n2])
    n1.raw_text = '!1 = !{ !2 }'

    match_result = MatchResult(n1)
    output = format_ascii_tree(match_result)

    expected = """!1 = !{ !2 }
 └─ [0]: !2 = !{ !3 }
     └─ [0]: !3 = <proxy>"""

    assert output == expected

def test_formatter_verbose_output():
    n1 = MDNode("1")
    n2 = MDNode("2")

    n1._target = MDSpecializedNode("DW_TAG_1", {"name": "n1", "child": n2})
    n1.raw_text = '!1 = !DW_TAG_1(name: "n1", child: !2)'

    n2._target = MDSpecializedNode("DW_TAG_2", {"name": "n2"})
    n2.raw_text = '!2 = !DW_TAG_2(name: "n2")'

    match_result = MatchResult(n1)

    # Test compact (default)
    output_compact = format_ascii_tree(match_result, verbose=False)
    expected_compact = """!1 = !DW_TAG_1(name: "n1", child: !2)
 └─ !2 = !DW_TAG_2(name: "n2")"""
    assert output_compact == expected_compact

    # Test verbose
    output_verbose = format_ascii_tree(match_result, verbose=True)
    expected_verbose = """!1 = !DW_TAG_1(name: "n1", child: !2)
 └─ child: !2 = !DW_TAG_2(name: "n2")"""
    assert output_verbose == expected_verbose

def test_formatter_shallow_output():
    n1 = MDNode("1")
    n2 = MDNode("2")

    n1._target = MDSpecializedNode("DW_TAG_1", {"name": "n1", "child": n2})
    n1.raw_text = '!1 = !DW_TAG_1(name: "n1", child: !2)'

    n2._target = MDSpecializedNode("DW_TAG_2", {"name": "n2"})
    n2.raw_text = '!2 = !DW_TAG_2(name: "n2")'

    match_result = MatchResult(n1)

    # Test shallow
    output_shallow = format_ascii_tree(match_result, depth=0)
    expected_shallow = '!1 = !DW_TAG_1(name: "n1", child: !2)'
    assert output_shallow == expected_shallow

