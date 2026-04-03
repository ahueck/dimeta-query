from dimeta_query.model import MDNode, MDSpecializedNode
from dimeta_query.reducers import (
    calculate_shortest_unique_suffixes,
    get_full_path,
    reduce_difile_nodes,
    regenerate_difile_text,
)


def test_calculate_shortest_unique_suffixes():
    paths = [
        "src/Kripke/Kernel.h",
        "tpl/raja/Kernel.h",
        "src/Kripke/Core/Data.cpp",
        "src/Kripke/Generate/Data.cpp",
        "single.h",
        "/absolute/path/file.c",
        "/other/absolute/path/file.c"
    ]

    results = calculate_shortest_unique_suffixes(paths)

    assert results["src/Kripke/Kernel.h"] == "Kripke/Kernel.h"
    assert results["tpl/raja/Kernel.h"] == "raja/Kernel.h"
    assert results["src/Kripke/Core/Data.cpp"] == "Core/Data.cpp"
    assert results["src/Kripke/Generate/Data.cpp"] == "Generate/Data.cpp"
    assert results["single.h"] == "single.h"
    assert results["/absolute/path/file.c"] == "/absolute/path/file.c"
    assert results["/other/absolute/path/file.c"] == "other/absolute/path/file.c"

def test_calculate_shortest_unique_suffixes_collision():
    # One is a suffix of another
    paths = [
        "Kernel.h",
        "src/Kripke/Kernel.h"
    ]
    results = calculate_shortest_unique_suffixes(paths)

    # Kernel.h is a suffix of src/Kripke/Kernel.h.
    # Our algorithm should distinguish them.
    assert results["src/Kripke/Kernel.h"] == "Kripke/Kernel.h"
    assert results["Kernel.h"] == "Kernel.h"


def test_single_component_reduction():
    """Test that paths are reduced to just the last component when unique."""
    paths = ["a/b", "x/y"]
    results = calculate_shortest_unique_suffixes(paths)
    assert results["a/b"] == "b"
    assert results["x/y"] == "y"


def test_multi_level_reduction():
    """Test that multi-level paths are reduced to just last component when unique."""
    paths = ["a/b/c", "x/y/z"]
    results = calculate_shortest_unique_suffixes(paths)
    assert results["a/b/c"] == "c"
    assert results["x/y/z"] == "z"


def test_single_vs_multi_level():
    """Test that single and multi-level paths with same suffix are distinguished."""
    paths = ["a/b", "x/a/b"]
    results = calculate_shortest_unique_suffixes(paths)
    assert results["a/b"] == "a/b"
    assert results["x/a/b"] == "x/a/b"


def test_regenerate_difile_text():
    node = MDNode("1")
    node.is_distinct = True
    target = MDSpecializedNode("DIFile", {
        "filename": "Kernel.h",
        "directory": "src/Kripke"
    })
    node._target = target

    text = regenerate_difile_text(node)
    expected = '!1 = distinct !DIFile(filename: "Kernel.h", directory: "src/Kripke")'
    assert text == expected

    node2 = MDNode("2")
    node2.is_distinct = False
    target2 = MDSpecializedNode("DIFile", {
        "filename": "main.c",
        "directory": ""
    })
    node2._target = target2
    expected = '!2 = !DIFile(filename: "main.c", directory: "")'
    assert regenerate_difile_text(node2) == expected

def test_reduce_difile_nodes():
    node1 = MDNode("1")
    node1.is_distinct = True
    node1._target = MDSpecializedNode("DIFile", {
        "filename": "Kernel.h",
        "directory": "/work/src/Kripke",
        "checksumkind": "CSK_MD5",
        "checksum": "12345"
    })
    node1.raw_text = (
        '!1 = distinct !DIFile(filename: "Kernel.h", '
        'directory: "/work/src/Kripke", checksumkind: CSK_MD5, checksum: "12345")'
    )

    node2 = MDNode("2")
    node2._target = MDSpecializedNode("DIFile", {
        "filename": "Kernel.h",
        "directory": "/work/tpl/raja",
        "checksumkind": "CSK_MD5",
        "checksum": "67890"
    })
    node2.raw_text = (
        '!2 = !DIFile(filename: "Kernel.h", directory: "/work/tpl/raja", '
        'checksumkind: CSK_MD5, checksum: "67890")'
    )

    node_map = {"1": node1, "2": node2}

    count = reduce_difile_nodes(node_map)
    assert count == 2

    assert node1._target.properties["filename"] == "Kernel.h"
    assert node1._target.properties["directory"] == "Kripke"
    assert "checksum" not in node1._target.properties
    assert "checksumkind" not in node1._target.properties
    assert node1.raw_text == (
        '!1 = distinct !DIFile(filename: "Kernel.h", directory: "Kripke")'
    )

    assert node2._target.properties["filename"] == "Kernel.h"
    assert node2._target.properties["directory"] == "raja"
    assert node2.raw_text == '!2 = !DIFile(filename: "Kernel.h", directory: "raja")'

def test_get_full_path():
    node = MDNode("1")
    node._target = MDSpecializedNode("DIFile", {
        "filename": "f.c",
        "directory": "/dir"
    })
    assert get_full_path(node) == "/dir/f.c"

    node2 = MDNode("2")
    node2._target = MDSpecializedNode("DIFile", {
        "filename": "/abs/f.c",
        "directory": "/dir"
    })
    assert get_full_path(node2) == "/abs/f.c"
