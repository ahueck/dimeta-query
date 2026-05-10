from dimeta_query.parser import parse_metadata


def test_node_id_stripping():
    # !0 = !{!"test"}
    node = parse_metadata('!0 = !{!"test"}')
    assert node.id == "0"
    assert isinstance(node.id, str)

def test_named_metadata_id_stripping():
    node = parse_metadata('!llvm.dbg.cu = !{!0}')
    assert node.id == "llvm.dbg.cu"
    assert isinstance(node.id, str)

def test_dwarf_tag_interning():
    line1 = '!0 = !DICompileUnit(language: DW_LANG_C99)'
    line2 = '!1 = !DIFile(tag: DW_LANG_C99)'

    node1 = parse_metadata(line1)
    val1 = node1._target.properties['language']

    assert val1 == "DW_LANG_C99"

    node2 = parse_metadata(line2)
    val2 = node2._target.properties['tag']

    assert val2 == "DW_LANG_C99"

    # Interning check
    assert val1 is val2

