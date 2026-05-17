import pytest

from dimeta_query.model import MDNode, MDSpecializedNode
from dimeta_query.unparser import DanglingReferenceError, Unparser


def test_unparser_raises_dangling_reference_error():
    node_map = {}

    n1 = MDNode("1")
    n1.raw_text = "!1 = ..."
    n2 = MDNode("2")
    n2.raw_text = "!2 = ..."
    n3 = MDNode("3")
    n3.raw_text = "!3 = ..."

    n1._target = MDSpecializedNode("DW_TAG_1", {"child": n2})
    n2._target = MDSpecializedNode("DW_TAG_2", {"child": n3})
    n3._target = MDSpecializedNode("DW_TAG_3", {})

    node_map["1"] = n1
    node_map["2"] = n2
    node_map["3"] = n3

    unparser = Unparser()

    # Should not raise
    unparser.validate(node_map)

    # Remove n3 from map
    del node_map["3"]

    with pytest.raises(DanglingReferenceError) as exc:
        unparser.validate(node_map)

    assert "dangling reference" in str(exc.value).lower()
    assert "missing node !3" in str(exc.value).lower()

def test_unparser_flags_proxy_as_dangling_reference():
    # Case where node is in map but has no definition (raw_text)
    node_map = {}

    n1 = MDNode("1")
    n1.raw_text = "!1 = !{!2}"
    n2 = MDNode("2")
    # n2 has no raw_text (proxy)

    n1._target = MDSpecializedNode("DW_TAG_1", {"child": n2})
    node_map["1"] = n1
    node_map["2"] = n2

    unparser = Unparser()
    with pytest.raises(DanglingReferenceError) as exc:
        unparser.validate(node_map)

    assert "dangling reference" in str(exc.value).lower()
    assert "dropped node !2" in str(exc.value).lower()
