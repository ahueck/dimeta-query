
import pytest

from dimeta_query.ir import IRManager
from dimeta_query.unparser import DanglingReferenceError


def test_ir_manager_init():
    manager = IRManager()
    assert manager.node_map == {}
    assert manager.ir_lines == []
    assert manager.ir_refs == {}
    assert manager.metadata_count == 0
    assert manager.unresolved == []

def test_ir_manager_parse_file(tmp_path):
    ll_content = [
        '; ModuleID = "test.ll"',
        'define void @foo() !dbg !1 {',
        '  ret void, !dbg !2',
        '}',
        '!1 = !DISubprogram(name: "foo", scope: !3)',
        '!2 = !DILocation(line: 1, column: 1, scope: !1)',
        '!3 = !DIFile(filename: "test.c", directory: "/tmp")'
    ]
    ll_file = tmp_path / "test.ll"
    ll_file.write_text("\n".join(ll_content) + "\n")

    manager = IRManager()
    manager.parse_file(str(ll_file))

    assert manager.metadata_count == 3
    assert len(manager.node_map) == 3
    assert len(manager.ir_lines) == 4
    assert "1" in manager.node_map
    assert "2" in manager.node_map
    assert "3" in manager.node_map

    # Check IR references
    # line 1 (idx 1): !1 (dbg)
    # line 2 (idx 2): !2 (dbg)
    assert "1" in manager.ir_refs
    assert ("dbg", 1) in manager.ir_refs["1"]
    assert "2" in manager.ir_refs
    assert ("dbg", 2) in manager.ir_refs["2"]

def test_ir_manager_unresolved(tmp_path):
    ll_content = [
        '!1 = !DISubprogram(name: "foo", scope: !2)'
    ]
    ll_file = tmp_path / "unresolved.ll"
    ll_file.write_text("\n".join(ll_content) + "\n")

    manager = IRManager()
    manager.parse_file(str(ll_file))

    assert manager.metadata_count == 1
    assert "2" in manager.node_map
    assert manager.node_map["2"]._target is None
    assert "2" in manager.unresolved

def test_ir_manager_file_not_found():
    manager = IRManager()
    with pytest.raises(FileNotFoundError):
        manager.parse_file("non_existent_file.ll")

def test_ir_manager_complex_refs(tmp_path):
    ll_content = [
        '#dbg_value(!1, !2, !DIExpression(), !3)',
        'call void @llvm.dbg.declare(metadata !4, metadata !5, '
        'metadata !DIExpression()), !dbg !6',
        '!1 = !{!"val"}',
        '!2 = !DILocalVariable(name: "v", scope: !7)',
        '!3 = !DILocation(line: 1, column: 1, scope: !7)',
        '!4 = !{!"ptr"}',
        '!5 = !DILocalVariable(name: "p", scope: !7)',
        '!6 = !DILocation(line: 2, column: 1, scope: !7)',
        '!7 = !DISubprogram(name: "bar")'
    ]
    ll_file = tmp_path / "complex.ll"
    ll_file.write_text("\n".join(ll_content) + "\n")

    manager = IRManager()
    manager.parse_file(str(ll_file))

    # #dbg_value(!1, !2, ..., !3) -> line 0
    assert ("dbg_value", 0) in manager.ir_refs["1"]
    assert ("dbg_value", 0) in manager.ir_refs["2"]
    assert ("dbg_value", 0) in manager.ir_refs["3"]

    # call @llvm.dbg.declare(..., !5, ...) !dbg !6 -> line 1
    assert ("dbg_declare", 1) in manager.ir_refs["4"]
    assert ("dbg_declare", 1) in manager.ir_refs["5"]
    assert ("dbg", 1) in manager.ir_refs["6"]

def test_ir_manager_save_file(tmp_path):
    ll_content = [
        '; ModuleID = "test.ll"',
        'define void @foo() {',
        '  ret void',
        '}',
        '!1 = !{!"first"}',
        '!2 = !{!"second"}',
        '!llvm.module.flags = !{!1}'
    ]
    ll_file = tmp_path / "test.ll"
    ll_file.write_text("\n".join(ll_content) + "\n")

    manager = IRManager()
    manager.parse_file(str(ll_file))

    save_file = tmp_path / "saved.ll"
    manager.save_file(str(save_file))

    assert save_file.exists()
    saved_content = save_file.read_text().splitlines()
    # IR lines should be preserved
    assert '; ModuleID = "test.ll"' in saved_content
    assert 'define void @foo() {' in saved_content
    # Metadata should be preserved and sorted
    assert '!1 = !{!"first"}' in saved_content
    assert '!2 = !{!"second"}' in saved_content
    assert '!llvm.module.flags = !{!1}' in saved_content
    
    # Check sorting: !llvm (named), then !1, !2 (numeric)
    metadata_lines = [line for line in saved_content if line.startswith('!')]
    assert metadata_lines[0].startswith('!llvm')
    assert metadata_lines[1].startswith('!1')
    assert metadata_lines[2].startswith('!2')

def test_ir_manager_save_dangling(tmp_path):
    # !1 references !2, but !2 is not defined
    ll_content = [
        '!1 = !{!2}'
    ]
    ll_file = tmp_path / "dangling.ll"
    ll_file.write_text("\n".join(ll_content) + "\n")

    manager = IRManager()
    manager.parse_file(str(ll_file))
    
    # Manually remove !2 from node_map to simulate it being dropped
    # Actually validate_graph doesn't remove it, it just marks it as unresolved
    # Unparser.validate raises DanglingReferenceError if child.id not in node_map
    del manager.node_map["2"]

    save_file = tmp_path / "fail.ll"
    with pytest.raises(DanglingReferenceError):
        manager.save_file(str(save_file))

def test_ir_manager_metadata_ordering(tmp_path):
    ll_content = [
        '!1 = !{!"numeric"}',
        '!foo = !{!"named"}',
        '!2 = !{!"numeric2"}',
        '!bar = !{!"named2"}'
    ]
    ll_file = tmp_path / "ordering.ll"
    ll_file.write_text("\n".join(ll_content) + "\n")

    manager = IRManager()
    manager.parse_file(str(ll_file))

    save_file = tmp_path / "saved_ordering.ll"
    manager.save_file(str(save_file))

    saved_content = save_file.read_text().splitlines()
    metadata_lines = [line for line in saved_content if line.startswith('!')]

    # Expectation: string IDs (!bar, !foo) come before numeric IDs (!1, !2)
    # And within each group, they are sorted (bar < foo, 1 < 2)
    assert len(metadata_lines) == 4
    assert metadata_lines[0].startswith('!bar')
    assert metadata_lines[1].startswith('!foo')
    assert metadata_lines[2].startswith('!1')
    assert metadata_lines[3].startswith('!2')

def test_ir_manager_numeric_sorting(tmp_path):
    ll_content = [
        '!19 = !{!"nineteen"}',
        '!2 = !{!"two"}',
        '!20 = !{!"twenty"}',
        '!200 = !{!"twohundred"}'
    ]
    ll_file = tmp_path / "sorting.ll"
    ll_file.write_text("\n".join(ll_content) + "\n")

    manager = IRManager()
    manager.parse_file(str(ll_file))

    save_file = tmp_path / "saved_sorting.ll"
    manager.save_file(str(save_file))

    saved_content = save_file.read_text().splitlines()
    metadata_lines = [line for line in saved_content if line.startswith('!')]
    
    ids = [line.split(' = ')[0] for line in metadata_lines]
    expected_ids = ['!2', '!19', '!20', '!200']
    assert ids == expected_ids

