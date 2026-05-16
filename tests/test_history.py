"""Tests for the undo/redo history feature."""

from unittest.mock import patch

import pytest

import dimeta_query.cli as cli
from dimeta_query.history import (
    DEFAULT_HISTORY_DEPTH,
    GraphSnapshot,
    HistoryManager,
)
from dimeta_query.ir import IRManager

# ---------------------------------------------------------------------------
# Unit tests: GraphSnapshot and HistoryManager
# ---------------------------------------------------------------------------


def _make_manager_with(content: list[str], tmp_path) -> IRManager:
    f = tmp_path / "snap.ll"
    f.write_text("\n".join(content) + "\n")
    manager = IRManager()
    manager.parse_file(str(f))
    return manager


def test_default_history_depth_is_five():
    assert DEFAULT_HISTORY_DEPTH == 5


def test_history_manager_invalid_depth():
    with pytest.raises(ValueError):
        HistoryManager(max_depth=0)


def test_snapshot_captures_and_restores_state(tmp_path):
    manager = _make_manager_with(
        [
            '!1 = !DIFile(filename: "a.c", directory: "/x")',
            '!2 = !DIBasicType(name: "int", size: 32)',
        ],
        tmp_path,
    )
    snap = GraphSnapshot.capture(manager)

    # Mutate
    del manager.node_map["1"]
    manager.metadata_count -= 1

    assert "1" not in manager.node_map
    snap.restore(manager)
    assert "1" in manager.node_map
    assert "2" in manager.node_map
    assert manager.metadata_count == 2


def test_snapshot_preserves_intra_graph_identity(tmp_path):
    manager = _make_manager_with(
        [
            '!1 = !DIBasicType(name: "int", size: 32)',
            '!2 = !DICompositeType(tag: DW_TAG_array_type, baseType: !1, size: 64)',
        ],
        tmp_path,
    )

    snap = GraphSnapshot.capture(manager)
    # Wipe everything
    manager.node_map = {}
    snap.restore(manager)

    # Restored composite should still reference the same restored basic type.
    composite = manager.node_map["2"]
    base = manager.node_map["1"]
    assert composite._target.properties["baseType"] is base


def test_snapshot_restore_is_reusable_for_redo(tmp_path):
    """Restoring a snapshot must not consume it - redo restores again."""
    manager = _make_manager_with(
        ['!1 = !{!"keep"}'],
        tmp_path,
    )
    snap = GraphSnapshot.capture(manager)

    manager.node_map.clear()
    snap.restore(manager)
    assert "1" in manager.node_map

    # Mutate and restore once more from the same snapshot
    manager.node_map.clear()
    snap.restore(manager)
    assert "1" in manager.node_map


def test_history_manager_record_clears_redo(tmp_path):
    manager = _make_manager_with(['!1 = !{!"x"}'], tmp_path)
    hist = HistoryManager(max_depth=5)

    s1 = GraphSnapshot.capture(manager)
    hist.record("op1", s1)

    # Move op1 into redo via undo
    current = GraphSnapshot.capture(manager)
    hist.undo(current)
    assert hist.can_redo()

    # New record must clear redo stack
    s2 = GraphSnapshot.capture(manager)
    hist.record("op2", s2)
    assert not hist.can_redo()


def test_history_manager_undo_redo_roundtrip(tmp_path):
    manager = _make_manager_with(['!1 = !{!"x"}'], tmp_path)
    hist = HistoryManager(max_depth=3)

    s1 = GraphSnapshot.capture(manager)
    hist.record("op1", s1)

    # Simulate a mutation
    manager.node_map.clear()

    cur = GraphSnapshot.capture(manager)
    result = hist.undo(cur)
    assert result is not None
    label, snap = result
    assert label == "op1"
    snap.restore(manager)
    assert "1" in manager.node_map

    # Now redo should bring us back to empty
    cur2 = GraphSnapshot.capture(manager)
    redo_res = hist.redo(cur2)
    assert redo_res is not None
    _, redo_snap = redo_res
    redo_snap.restore(manager)
    assert "1" not in manager.node_map


def test_history_manager_empty_returns_none():
    hist = HistoryManager()
    dummy = GraphSnapshot(
        node_map={}, ir_lines=[], ir_refs={}, metadata_count=0, unresolved=[]
    )
    assert hist.undo(dummy) is None
    assert hist.redo(dummy) is None
    assert not hist.can_undo()
    assert not hist.can_redo()


def test_history_manager_bounded_depth(tmp_path):
    manager = _make_manager_with(['!1 = !{!"x"}'], tmp_path)
    hist = HistoryManager(max_depth=3)

    for i in range(7):
        snap = GraphSnapshot.capture(manager)
        hist.record(f"op{i}", snap)

    labels = hist.undo_labels()
    # Only the last 3 should remain (oldest first).
    assert labels == ["op4", "op5", "op6"]


# ---------------------------------------------------------------------------
# Integration tests: end-to-end through the CLI
# ---------------------------------------------------------------------------


def _collect_prints(mock_print) -> str:
    out = []
    for call_args, _ in mock_print.call_args_list:
        for arg in call_args:
            out.append(str(arg))
    return "\n".join(out)


def test_cli_undo_after_drop_restores_node(tmp_path):
    input_content = [
        '!0 = !{!"keep"}',
        '!1 = !{!"droppable"}',
    ]
    input_file = tmp_path / "undo_drop.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    output_file = tmp_path / "undo_drop_out.ll"

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input",
            side_effect=["drop !1", "undo", f"unparse {output_file}", "exit"],
        ):
            with patch("builtins.print") as mock_print:
                cli.main()
                out = _collect_prints(mock_print)
                assert "Success: Dropped !1" in out
                assert "Undone: drop !1" in out

    text = output_file.read_text()
    assert '!1 = !{!"droppable"}' in text
    assert '!0 = !{!"keep"}' in text


def test_cli_redo_after_undo_reapplies_drop(tmp_path):
    input_content = [
        '!0 = !{!"keep"}',
        '!1 = !{!"droppable"}',
    ]
    input_file = tmp_path / "redo_drop.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    output_file = tmp_path / "redo_drop_out.ll"

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input",
            side_effect=[
                "drop !1",
                "undo",
                "redo",
                f"unparse {output_file}",
                "exit",
            ],
        ):
            with patch("builtins.print") as mock_print:
                cli.main()
                out = _collect_prints(mock_print)
                assert "Undone: drop !1" in out
                assert "Redone: drop !1" in out

    text = output_file.read_text()
    assert '!1 = !{!"droppable"}' not in text
    assert '!0 = !{!"keep"}' in text


def test_cli_undo_after_sweep_restores_unreferenced(tmp_path):
    input_content = [
        "define void @foo() !dbg !0 {",
        "  ret void",
        "}",
        '!0 = !{!"keep"}',
        '!1 = !{!"orphan"}',
    ]
    input_file = tmp_path / "undo_sweep.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    output_file = tmp_path / "undo_sweep_out.ll"

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input",
            side_effect=["sweep", "undo", f"unparse {output_file}", "exit"],
        ):
            with patch("builtins.print") as mock_print:
                cli.main()
                out = _collect_prints(mock_print)
                assert "Swept 1 unreferenced metadata definitions" in out
                assert "Undone: sweep" in out

    text = output_file.read_text()
    # Both nodes should be restored.
    assert '!0 = !{!"keep"}' in text
    assert '!1 = !{!"orphan"}' in text


def test_cli_undo_after_sweep_reduce_restores_difile(tmp_path):
    original_difile = '!1 = !DIFile(filename: "src/a.c", directory: "/home/user/proj")'
    input_content = [
        original_difile,
        "!llvm.module.flags = !{!1}",
    ]
    input_file = tmp_path / "undo_reduce.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    output_file = tmp_path / "undo_reduce_out.ll"

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input",
            side_effect=["sweep -r", "undo", f"unparse {output_file}", "exit"],
        ):
            with patch("builtins.print"):
                cli.main()

    text = output_file.read_text()
    # After undo, the original directory and filename strings should be back.
    assert 'directory: "/home/user/proj"' in text
    assert 'filename: "src/a.c"' in text


def test_cli_undo_when_empty(tmp_path):
    input_file = tmp_path / "empty.ll"
    input_file.write_text('!0 = !{!"x"}\n')

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch("builtins.input", side_effect=["undo", "exit"]):
            with patch("builtins.print") as mock_print:
                cli.main()
                out = _collect_prints(mock_print)
                assert "Nothing to undo." in out


def test_cli_redo_when_empty(tmp_path):
    input_file = tmp_path / "empty_redo.ll"
    input_file.write_text('!0 = !{!"x"}\n')

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch("builtins.input", side_effect=["redo", "exit"]):
            with patch("builtins.print") as mock_print:
                cli.main()
                out = _collect_prints(mock_print)
                assert "Nothing to redo." in out


def test_cli_new_mutation_clears_redo(tmp_path):
    input_content = [
        '!0 = !{!"a"}',
        '!1 = !{!"b"}',
        '!2 = !{!"c"}',
    ]
    input_file = tmp_path / "clear_redo.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input",
            side_effect=[
                "drop !1",
                "undo",      # !1 back, redo has the drop
                "drop !2",   # this should clear redo
                "redo",      # should now report Nothing to redo
                "exit",
            ],
        ):
            with patch("builtins.print") as mock_print:
                cli.main()
                out = _collect_prints(mock_print)
                assert "Nothing to redo." in out


def test_cli_history_command_lists_labels(tmp_path):
    input_content = [
        '!0 = !{!"a"}',
        '!1 = !{!"b"}',
        '!2 = !{!"c"}',
    ]
    input_file = tmp_path / "history_cmd.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input",
            side_effect=["drop !1", "drop !2", "undo", "history", "exit"],
        ):
            with patch("builtins.print") as mock_print:
                cli.main()
                out = _collect_prints(mock_print)
                assert "Undo stack" in out
                assert "drop !1" in out
                assert "Redo stack" in out
                assert "drop !2" in out


def test_cli_history_empty(tmp_path):
    input_file = tmp_path / "empty_history.ll"
    input_file.write_text('!0 = !{!"x"}\n')

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch("builtins.input", side_effect=["history", "exit"]):
            with patch("builtins.print") as mock_print:
                cli.main()
                out = _collect_prints(mock_print)
                assert "History is empty." in out


def test_cli_readonly_commands_do_not_affect_history(tmp_path):
    input_file = tmp_path / "readonly.ll"
    input_file.write_text(
        '!0 = !DIBasicType(name: "int", size: 32)\n'
    )

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input",
            side_effect=[
                'm basic_type(has_name("int"))',
                "p !0",
                "history",
                "exit",
            ],
        ):
            with patch("builtins.print") as mock_print:
                cli.main()
                out = _collect_prints(mock_print)
                # No mutation occurred - history should be reported empty.
                assert "History is empty." in out


def test_cli_failed_drop_does_not_record_history(tmp_path):
    """A drop that fails due to active references must not leave a snapshot."""
    input_content = [
        '!0 = !{!1}',
        '!1 = !{!"referenced"}',
    ]
    input_file = tmp_path / "failed_drop.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input",
            side_effect=["drop !1", "history", "exit"],
        ):
            with patch("builtins.print") as mock_print:
                cli.main()
                out = _collect_prints(mock_print)
                assert "Failed to drop !1" in out
                assert "History is empty." in out


def test_cli_undo_chain_multiple_drops(tmp_path):
    input_content = [
        '!0 = !{!"a"}',
        '!1 = !{!"b"}',
        '!2 = !{!"c"}',
    ]
    input_file = tmp_path / "undo_chain.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    output_file = tmp_path / "undo_chain_out.ll"

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input",
            side_effect=[
                "drop !1",
                "drop !2",
                "undo",
                "undo",
                f"unparse {output_file}",
                "exit",
            ],
        ):
            with patch("builtins.print"):
                cli.main()

    text = output_file.read_text()
    # Both nodes should be back after two undos.
    assert '!1 = !{!"b"}' in text
    assert '!2 = !{!"c"}' in text


def test_cli_history_depth_bound_via_cli(tmp_path):
    """End-to-end: history depth is bounded as configured."""
    # We can't change DEFAULT_HISTORY_DEPTH from outside, but we can verify
    # behavior at the boundary by performing more than DEFAULT_HISTORY_DEPTH
    # operations and confirming we cannot undo more than the bound.
    nodes = [f'!{i} = !{{!"n{i}"}}' for i in range(DEFAULT_HISTORY_DEPTH + 3)]
    input_file = tmp_path / "depth_bound.ll"
    input_file.write_text("\n".join(nodes) + "\n")

    drops = [f"drop !{i}" for i in range(DEFAULT_HISTORY_DEPTH + 3)]
    # After all drops, attempt undo (depth + 3) times. Only depth undos
    # should succeed.
    undos = ["undo"] * (DEFAULT_HISTORY_DEPTH + 3)

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch("builtins.input", side_effect=drops + undos + ["exit"]):
            with patch("builtins.print") as mock_print:
                cli.main()
                out = _collect_prints(mock_print)
                # Number of "Nothing to undo." messages should be exactly 3.
                assert out.count("Nothing to undo.") == 3
                # And number of successful undo messages should be == depth.
                assert out.count("Undone: ") == DEFAULT_HISTORY_DEPTH
