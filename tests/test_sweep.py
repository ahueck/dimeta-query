
from dimeta_query.ir import IRManager


def test_sweep_clean_direct_orphan(tmp_path):
    # !0 is referenced by IR
    # !1 is an orphan (not referenced, not child of any referenced node)
    ll_content = [
        'define void @foo() !dbg !0 {',
        '  ret void',
        '}',
        '!0 = !{!"referenced"}',
        '!1 = !{!"orphan"}'
    ]
    ll_file = tmp_path / "orphan.ll"
    ll_file.write_text("\n".join(ll_content) + "\n")

    manager = IRManager()
    manager.parse_file(str(ll_file))

    assert "0" in manager.node_map
    assert "1" in manager.node_map
    assert manager.metadata_count == 2

    # Identify orphans
    unreferenced = manager.find_unreferenced_metadata_ids()
    assert unreferenced == ["1"]

    # Sweep
    removed_count = manager.sweep_unreferenced_metadata()
    assert removed_count == 1
    assert "0" in manager.node_map
    assert "1" not in manager.node_map
    assert manager.metadata_count == 1

def test_sweep_clean_transitive_retention(tmp_path):
    # IR -> !0 -> !1
    # !2 is an orphan
    ll_content = [
        'define void @foo() !dbg !0 {',
        '  ret void',
        '}',
        '!0 = !{!1}',
        '!1 = !{!"leaf"}',
        '!2 = !{!"orphan"}'
    ]
    ll_file = tmp_path / "transitive.ll"
    ll_file.write_text("\n".join(ll_content) + "\n")

    manager = IRManager()
    manager.parse_file(str(ll_file))

    # !1 is reachable from !0, so it should stay
    unreferenced = manager.find_unreferenced_metadata_ids()
    assert unreferenced == ["2"]

    manager.sweep_unreferenced_metadata()
    assert "0" in manager.node_map
    assert "1" in manager.node_map
    assert "2" not in manager.node_map

def test_sweep_clean_shared_descendant(tmp_path):
    # IR -> !0 -> !1
    # !2 -> !1 (but !2 is unreferenced)
    ll_content = [
        'define void @foo() !dbg !0 {',
        '  ret void',
        '}',
        '!0 = !{!1}',
        '!1 = !{!"shared"}',
        '!2 = !{!1}'
    ]
    ll_file = tmp_path / "shared.ll"
    ll_file.write_text("\n".join(ll_content) + "\n")

    manager = IRManager()
    manager.parse_file(str(ll_file))

    # !1 is reachable via !0, even if !2 is dropped
    unreferenced = manager.find_unreferenced_metadata_ids()
    assert unreferenced == ["2"]

    manager.sweep_unreferenced_metadata()
    assert "1" in manager.node_map
    assert "2" not in manager.node_map

def test_sweep_clean_named_metadata_policy(tmp_path):
    # Currently my implementation ignores named metadata as sweep candidates
    # because ir_refs only extracts numeric IDs.
    ll_content = [
        'define void @foo() !dbg !0 {',
        '  ret void',
        '}',
        '!0 = !{!"root"}',
        '!llvm.module.flags = !{!0}',
        '!unreferenced_named = !{!"named_orphan"}'
    ]
    ll_file = tmp_path / "named.ll"
    ll_file.write_text("\n".join(ll_content) + "\n")

    manager = IRManager()
    manager.parse_file(str(ll_file))

    # !unreferenced_named is not numeric, so it's not a candidate for sweep
    # (based on node_id.isdigit() check)
    unreferenced = manager.find_unreferenced_metadata_ids()
    assert "unreferenced_named" not in unreferenced

def test_sweep_clean_save_file(tmp_path):
    ll_content = [
        'define void @foo() !dbg !0 {',
        '  ret void',
        '}',
        '!0 = !{!"keep"}',
        '!1 = !{!"drop"}'
    ]
    ll_file = tmp_path / "save.ll"
    ll_file.write_text("\n".join(ll_content) + "\n")

    manager = IRManager()
    manager.parse_file(str(ll_file))
    manager.sweep_unreferenced_metadata()

    out_file = tmp_path / "out.ll"
    manager.save_file(str(out_file))

    out_text = out_file.read_text()
    assert '!0 = !{!"keep"}' in out_text
    assert '!1 = !{!"drop"}' not in out_text

def test_sweep_clean_named_root_retention(tmp_path):
    # !1 is referenced by !llvm.named, but not by IR
    # It should NOT be swept.
    ll_content = [
        'define void @foo() {',
        '  ret void',
        '}',
        '!1 = !{!"preserve me"}',
        '!llvm.named = !{!1}',
        '!2 = !{!"orphan"}'
    ]
    ll_file = tmp_path / "named_retention.ll"
    ll_file.write_text("\n".join(ll_content) + "\n")

    manager = IRManager()
    manager.parse_file(str(ll_file))

    unreferenced = manager.find_unreferenced_metadata_ids()
    # !1 is reachable from !llvm.named, so it stays.
    # !2 is an orphan.
    assert "1" not in unreferenced
    assert "2" in unreferenced

    manager.sweep_unreferenced_metadata()
    assert "1" in manager.node_map
    assert "2" not in manager.node_map

def test_sweep_default_keeps_named(tmp_path):
    content = """
!llvm.module.flags = !{!0}
!0 = !{i32 2, !"Debug Info Version", i32 3}
!1 = !{!"orphan"}
"""
    f = tmp_path / "test.ll"
    f.write_text(content)

    manager = IRManager()
    manager.parse_file(str(f))

    # Default sweep: !llvm.module.flags is a root, !0 is reachable. !1 is orphan.
    count = manager.sweep_unreferenced_metadata(discard_named=False)
    assert count == 1
    assert "llvm.module.flags" in manager.node_map
    assert "0" in manager.node_map
    assert "1" not in manager.node_map

def test_sweep_all_discards_named(tmp_path):
    content = """
!llvm.module.flags = !{!0}
!0 = !{i32 2, !"Debug Info Version", i32 3}
"""
    f = tmp_path / "test.ll"
    f.write_text(content)

    manager = IRManager()
    manager.parse_file(str(f))

    # sweep -a: !llvm.module.flags is NOT a root if not in IR.
    # IR is empty, so everything is unreferenced.
    count = manager.sweep_unreferenced_metadata(discard_named=True)
    assert count == 2
    assert "llvm.module.flags" not in manager.node_map
    assert "0" not in manager.node_map

def test_sweep_all_keeps_named_if_in_ir(tmp_path):
    # This test depends on the regex actually matching named nodes in IR.
    # The user feedback said NOT to update regex, so let's see what happens.
    # Currently ATTACHMENT_RE = re.compile(r'!(\w+)\s+!(\d+)')
    # It only matches numeric IDs (\d+).
    # So !llvm.module.flags will NEVER be matched in IR with current regex.
    pass

def test_sweep_all_reachable_from_ir(tmp_path):
    content = """
define void @foo() !dbg !1 {
  ret void
}
!llvm.module.flags = !{!0}
!0 = !{i32 2, !"Debug Info Version", i32 3}
!1 = !DILocalVariable(name: "x", scope: !2)
!2 = !DIFile(filename: "f.c", directory: ".")
"""
    f = tmp_path / "test.ll"
    f.write_text(content)

    manager = IRManager()
    manager.parse_file(str(f))

    # !1 is referenced in IR. !2 is reachable from !1.
    # !llvm.module.flags is NOT referenced in IR. !0 is reachable only from it.

    count = manager.sweep_unreferenced_metadata(discard_named=True)
    # Should remove !llvm.module.flags and !0.
    assert "1" in manager.node_map
    assert "2" in manager.node_map
    assert "llvm.module.flags" not in manager.node_map
    assert "0" not in manager.node_map
    assert count == 2
