import os
from unittest.mock import MagicMock, patch

import dimeta_query.cli as cli


def test_setup_sandbox_globals():
    globals_dict = cli.setup_sandbox_globals()
    assert "node" in globals_dict
    assert "composite_type" in globals_dict
    assert "fuzzy" in globals_dict
    assert "has_tag" in globals_dict

def test_unparse_roundtrip(tmp_path):
    # Create a sorted test .ll file
    input_content = [
        '!1 = !DIFile(filename: "test.c", directory: "/tmp")',
        '!2 = !DICompositeType(tag: DW_TAG_array_type, baseType: !3, '
        'size: 64, align: 64)',
        '!3 = !DIBasicType(name: "int", size: 32, encoding: DW_ATE_signed)'
    ]

    input_file = tmp_path / "input.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    output_file = tmp_path / "output.ll"

    # Mock sys.argv to point to input.ll
    with patch("sys.argv", ["dimeta", str(input_file)]):
        # Mock input() to run 'unparse output.ll' and then 'exit'
        with patch("builtins.input", side_effect=[f"unparse {output_file}", "exit"]):
            # Suppress print output for cleaner test run
            with patch("builtins.print"):
                cli.main()

    # Check if output file exists and matches input content (sorted)
    assert output_file.exists()
    output_content = [
        line for line in output_file.read_text().split("\n") if line.strip()
    ]

    # Both should match perfectly because they are sorted
    assert output_content == input_content

def test_cli_drop_node(tmp_path):
    input_content = [
        '!1 = !DIFile(filename: "test.c", directory: "/tmp")',
        '!2 = !DICompositeType(tag: DW_TAG_array_type, baseType: !1, '
        'size: 64, align: 64)'
    ]
    input_file = tmp_path / "input.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    # Mock sys.argv and input to drop a node and exit
    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch("builtins.input", side_effect=["drop !2", "exit"]):
            with patch("builtins.print") as mock_print:
                cli.main()
                # Verify that some print message about dropping appeared
                assert any(
                    "Success: Dropped !2" in str(args)
                    for args, kwargs in mock_print.call_args_list
                )

def test_unparse_roundtrip_mixed_ids_stable(tmp_path):
    # Create a test .ll file with multiple non-numeric IDs
    # They should be sorted alphabetically and COME BEFORE numeric IDs
    input_content = [
        '!1 = !DIFile(filename: "test.c", directory: "/tmp")',
        '!llvm.dbg.cu = !{!1}',
        '!llvm.ident = !{!1}',
        '!llvm.module.flags = !{!1}'
    ]

    # Expected order: named metadata first, then numeric IDs
    expected_content = [
        '!llvm.dbg.cu = !{!1}',
        '!llvm.ident = !{!1}',
        '!llvm.module.flags = !{!1}',
        '!1 = !DIFile(filename: "test.c", directory: "/tmp")'
    ]

    input_file = tmp_path / "input_stable.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    output_file = tmp_path / "output_stable.ll"

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch("builtins.input", side_effect=[f"unparse {output_file}", "exit"]):
            with patch("builtins.print"):
                cli.main()

    assert output_file.exists()
    output_lines = [
        line for line in output_file.read_text().split("\n") if line.strip()
    ]

    assert output_lines == expected_content

def test_unparse_roundtrip_mixed_ids(tmp_path):
    # Create a test .ll file with mixed IDs
    input_content = [
        '!1 = !DIFile(filename: "test.c", directory: "/tmp")',
        '!llvm.dbg.cu = !{!1}'
    ]

    # Expected order: named metadata first, then numeric IDs
    expected_content = [
        '!llvm.dbg.cu = !{!1}',
        '!1 = !DIFile(filename: "test.c", directory: "/tmp")'
    ]

    input_file = tmp_path / "input_mixed.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    output_file = tmp_path / "output_mixed.ll"

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch("builtins.input", side_effect=[f"unparse {output_file}", "exit"]):
            with patch("builtins.print"):
                cli.main()

    assert output_file.exists()
    output_content = [
        line for line in output_file.read_text().split("\n") if line.strip()
    ]

    assert output_content == expected_content

def test_cli_demangle_matcher_itanium(tmp_path):
    input_content = [
        '!1 = !DISubprogram(name: "_Z3fooi")'
    ]
    input_file = tmp_path / "input_itanium.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input",
            side_effect=['m subprogram(has_name(demangle("foo(int)")))', "exit"],
        ):
            with patch("builtins.print") as mock_print:
                # Mock itanium_demangler module
                mock_itanium = MagicMock()
                mock_itanium.parse.return_value = "foo(int)"
                # Ensure cxxfilt is NOT found so it falls back to itanium_demangler
                with patch.dict(
                    "sys.modules", {"cxxfilt": None, "itanium_demangler": mock_itanium}
                ):
                    cli.main()
                    match_found = False
                    for call_args, _ in mock_print.call_args_list:
                        for arg in call_args:
                            if "Match 1 at !1" in str(arg):
                                match_found = True
                    assert match_found

def test_cli_matcher_query(tmp_path):
    input_content = [
        '!1 = !DIBasicType(name: "int", size: 32)'
    ]
    input_file = tmp_path / "input.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input", side_effect=['m basic_type(has_name("int"))', "exit"]
        ):
            with patch("builtins.print") as mock_print:
                cli.main()
                # Check for Match 1 in output
                match_found = False
                for call_args, _ in mock_print.call_args_list:
                    for arg in call_args:
                        if "Match 1 at !1" in str(arg):
                            match_found = True
                assert match_found

def test_cli_fuzzy_matcher(tmp_path):
    input_content = [
        '!1 = !DICompositeType(tag: DW_TAG_class_type, name: "TapeBaseModule")'
    ]
    input_file = tmp_path / "input_fuzzy.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input",
            side_effect=['m composite_type(has_name(fuzzy("Tape.*Module")))', "exit"],
        ):
            with patch("builtins.print") as mock_print:
                cli.main()
                match_found = False
                for call_args, _ in mock_print.call_args_list:
                    for arg in call_args:
                        if "Match 1 at !1" in str(arg):
                            match_found = True
                assert match_found

def test_cli_demangle_matcher(tmp_path):
    input_content = [
        '!1 = !DISubprogram(name: "_Z3fooi")'
    ]
    input_file = tmp_path / "input_demangle.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input",
            side_effect=['m subprogram(has_name(demangle("foo(int)")))', "exit"],
        ):
            with patch("builtins.print") as mock_print:
                # Mock cxxfilt module in sys.modules
                mock_cxxfilt = MagicMock()
                mock_cxxfilt.demangle.return_value = "foo(int)"
                with patch.dict("sys.modules", {"cxxfilt": mock_cxxfilt}):
                    cli.main()
                    match_found = False
                    for call_args, _ in mock_print.call_args_list:
                        for arg in call_args:
                            if "Match 1 at !1" in str(arg):
                                match_found = True
                    assert match_found

def test_unparse_preserves_ir(tmp_path):
    input_content = [
        '; ModuleID = \'test\'',
        'define void @foo() {',
        '  ret void',
        '}',
        '',
        '!0 = !{!"metadata"}'
    ]
    input_file = tmp_path / "input_ir.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    output_file = tmp_path / "output_ir.ll"

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch("builtins.input", side_effect=[f"unparse {output_file}", "exit"]):
            with patch("builtins.print"):
                cli.main()

    assert output_file.exists()
    output_text = output_file.read_text()

    # Check that IR parts are preserved exactly
    assert "define void @foo() {" in output_text
    assert "  ret void" in output_text
    assert "!0 = !{!\"metadata\"}" in output_text

def test_unparse_preserves_ir_with_drops(tmp_path):
    input_content = [
        'define void @foo() {',
        '  ret void',
        '}',
        '!0 = !{!"keep"}',
        '!1 = !{!"drop"}'
    ]
    input_file = tmp_path / "input_ir_drop.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    output_file = tmp_path / "output_ir_drop.ll"

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input",
            side_effect=["drop !1", f"unparse {output_file}", "exit"],
        ):
            with patch("builtins.print"):
                cli.main()

    assert output_file.exists()
    output_text = output_file.read_text()

    assert "define void @foo() {" in output_text
    assert "!0 = !{!\"keep\"}" in output_text
    assert "!1 = !{!\"drop\"}" not in output_text

def test_cli_force_drop(tmp_path):
    input_content = [
        'define void @foo() {',
        '  ret void',
        '}',
        '!0 = !{!1}',
        '!1 = !{!"referenced"}'
    ]
    input_file = tmp_path / "input_force.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    # Try to drop !1 without force - should fail
    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch("builtins.input", side_effect=["drop !1", "exit"]):
            with patch("builtins.print") as mock_print:
                cli.main()
                assert any(
                    "Failed to drop !1: Cannot drop node with active references"
                    in str(args)
                    for args, kwargs in mock_print.call_args_list
                )

    # Try to drop !1 with force - should succeed but warn
    output_file = tmp_path / "output_force.ll"
    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input",
            side_effect=["drop -f !1", f"unparse {output_file}", "exit"],
        ):
            with patch("builtins.print") as mock_print:
                cli.main()
                # Verify success message
                assert any(
                    "Success: Dropped !1 (force=True)" in str(args)
                    for args, kwargs in mock_print.call_args_list
                )
                # Verify inconsistency warning
                assert any(
                    "Warning: Graph is now inconsistent" in str(args)
                    for args, kwargs in mock_print.call_args_list
                )
                # Verify unparse failure message
                assert any(
                    "Unparse Error" in str(args)
                    for args, kwargs in mock_print.call_args_list
                )

    assert not output_file.exists()


def test_cli_overwrite(tmp_path):

    input_content = [
        'define void @foo() !dbg !0 {',
        '  ret void',
        '}',
        '!0 = !{!"keep"}',
        '!1 = !{!"drop"}'
    ]
    input_file = tmp_path / "input_sweep.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    output_file = tmp_path / "output_sweep.ll"

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input",
            side_effect=["sweep", f"unparse {output_file}", "exit"],
        ):
            with patch("builtins.print") as mock_print:
                cli.main()
                assert any(
                    "Success: Swept 1 unreferenced metadata definitions." in str(args)
                    for args, kwargs in mock_print.call_args_list
                )

    assert output_file.exists()
    output_text = output_file.read_text()
    assert '!0 = !{!"keep"}' in output_text
    assert '!1 = !{!"drop"}' not in output_text

def test_cli_combined_demangle_fuzzy(tmp_path):
    input_content = [
        '!1 = !DISubprogram(name: "_Z3fooi")'
    ]
    input_file = tmp_path / "input_combined.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input",
            side_effect=['m subprogram(has_name(demangle(fuzzy("foo.*"))))', "exit"],
        ):
            with patch("builtins.print") as mock_print:
                mock_cxxfilt = MagicMock()
                mock_cxxfilt.demangle.return_value = "foo(int)"
                with patch.dict("sys.modules", {"cxxfilt": mock_cxxfilt}):
                    cli.main()
                    match_found = False
                    for call_args, _ in mock_print.call_args_list:
                        for arg in call_args:
                            if "Match 1 at !1" in str(arg):
                                match_found = True
                    assert match_found

def test_cli_node_only_flag(tmp_path):
    input_content = [
        '!1 = !DICompositeType(tag: DW_TAG_structure_type, '
        'name: "MyStruct", elements: !2)',
        '!2 = !{ !3 }',
        '!3 = !DIBasicType(name: "int", size: 32)'
    ]
    input_file = tmp_path / "input.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    # query with -n
    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input",
            side_effect=['m -n composite_type(has_name("MyStruct"))', "exit"]
        ):
            with patch("builtins.print") as mock_print:
                cli.main()

                # Collect all printed lines
                printed_lines = []
                for call_args, _ in mock_print.call_args_list:
                    for arg in call_args:
                        printed_lines.append(str(arg))

                full_output = "\n".join(printed_lines)

                # Should find the match
                assert "Match 1 at !1" in full_output
                # Should show the root node
                assert (
                    '!1 = !DICompositeType(tag: DW_TAG_structure_type, '
                    'name: "MyStruct", elements: !2)'
                ) in full_output
                # Should NOT show the child node !3 or the tree structure
                assert "└─" not in full_output
                assert "!3 = !DIBasicType" not in full_output

def test_cli_node_only_long_flag(tmp_path):
    input_content = [
        '!1 = !DICompositeType(tag: DW_TAG_structure_type, '
        'name: "MyStruct", elements: !2)',
        '!2 = !{ !3 }',
        '!3 = !DIBasicType(name: "int", size: 32)'
    ]
    input_file = tmp_path / "input.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    # query with --node-only
    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input",
            side_effect=['m --node-only composite_type(has_name("MyStruct"))', "exit"]
        ):
            with patch("builtins.print") as mock_print:
                cli.main()

                printed_lines = []
                for call_args, _ in mock_print.call_args_list:
                    for arg in call_args:
                        printed_lines.append(str(arg))

                full_output = "\n".join(printed_lines)

                assert "Match 1 at !1" in full_output
                assert (
                    '!1 = !DICompositeType(tag: DW_TAG_structure_type, '
                    'name: "MyStruct", elements: !2)'
                ) in full_output
                assert "└─" not in full_output

def test_cli_mixed_flags(tmp_path):
    # Verify that -n and -v can coexist (though -n suppresses the tree,
    # so -v might be redundant for the tree structure, but the code
    # shouldn't crash and should respect -n)
    input_content = [
        '!1 = !DICompositeType(tag: DW_TAG_structure_type, '
        'name: "MyStruct", elements: !2)',
        '!2 = !{ !3 }',
        '!3 = !DIBasicType(name: "int", size: 32)'
    ]
    input_file = tmp_path / "input.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input",
            side_effect=['m -n -v composite_type(has_name("MyStruct"))', "exit"]
        ):
            with patch("builtins.print") as mock_print:
                cli.main()

                printed_lines = []
                for call_args, _ in mock_print.call_args_list:
                    for arg in call_args:
                        printed_lines.append(str(arg))

                full_output = "\n".join(printed_lines)

                assert "Match 1 at !1" in full_output
                # Shallow should win over verbose in terms of recursion
                assert "└─" not in full_output

def test_cli_print_node(tmp_path):
    input_content = [
        '!1 = !DIFile(filename: "test.c", directory: "/tmp")',
        '!2 = !DICompositeType(tag: DW_TAG_structure_type, '
        'name: "MyStruct", elements: !3)',
        '!3 = !{ !4 }',
        '!4 = !DIBasicType(name: "int", size: 32)'
    ]
    input_file = tmp_path / "input.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    # Test p !2 (deep default)
    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input",
            side_effect=['p !2', "exit"]
        ):
            with patch("builtins.print") as mock_print:
                cli.main()

                output = []
                for call_args, _ in mock_print.call_args_list:
                    for arg in call_args:
                        output.append(str(arg))
                full_output = "\n".join(output)

                assert "Node !2:" in full_output
                assert "MyStruct" in full_output
                assert "└─" in full_output

    # Test p -n !2 (shallow)
    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch("builtins.input", side_effect=['p -n !2', "exit"]):
            with patch("builtins.print") as mock_print:
                cli.main()

                output = []
                for call_args, _ in mock_print.call_args_list:
                    for arg in call_args:
                        output.append(str(arg))
                full_output = "\n".join(output)

                assert "Node !2:" in full_output
                assert "MyStruct" in full_output
                assert "└─" not in full_output

    # Test p 2 (numeric ID without !)
    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch("builtins.input", side_effect=['p 2', "exit"]):
            with patch("builtins.print") as mock_print:
                cli.main()

                output = []
                for call_args, _ in mock_print.call_args_list:
                    for arg in call_args:
                        output.append(str(arg))
                full_output = "\n".join(output)

                assert "Node !2:" in full_output
                assert "MyStruct" in full_output

    # Check for invalid node
    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch("builtins.input", side_effect=['p !999', "exit"]):
            with patch("builtins.print") as mock_print:
                cli.main()

                output = []
                for call_args, _ in mock_print.call_args_list:
                    for arg in call_args:
                        output.append(str(arg))
                full_output = "\n".join(output)

                assert "Error: Node !999 not found" in full_output


def test_cli_drop_matcher(tmp_path):
    input_content = [
        '!1 = !DIFile(filename: "test.c", directory: "/tmp")',
        '!2 = !DIBasicType(name: "int", size: 32)'
    ]
    input_file = tmp_path / "input_drop_matcher.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    # Matcher: drop all DIBasicType
    output_file = tmp_path / "output_drop_matcher.ll"
    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch(
            "builtins.input",
            side_effect=[
                'drop basic_type(has_name("int"))',
                f"unparse {output_file}",
                "exit",
            ],
        ):
            with patch("builtins.print") as mock_print:
                cli.main()
                assert any(
                    "Success: Dropped 1 matching nodes (force=False)" in str(args)
                    for args, kwargs in mock_print.call_args_list
                )

    assert output_file.exists()
    out_text = output_file.read_text()
    assert '!2 = !DIBasicType(name: "int", size: 32)' not in out_text

def test_cli_drop_matcher_force(tmp_path):
    input_content = [
        '!1 = !DIFile(filename: "test.c", directory: "/tmp")',
        '!2 = !DICompositeType(tag: DW_TAG_array_type, baseType: !1, size: 64)'
    ]
    input_file = tmp_path / "input_drop_matcher_force.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    # Try to drop !1 without force - should fail
    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch("builtins.input", side_effect=['drop file_node()', "exit"]):
            with patch("builtins.print") as mock_print:
                cli.main()
                assert any(
                    "Failed to drop !1: Cannot drop node with active references"
                    in str(args)
                    for args, kwargs in mock_print.call_args_list
                )

    # Try to drop with force
    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch("builtins.input", side_effect=['drop -f file_node()', "exit"]):
            with patch("builtins.print") as mock_print:
                cli.main()
                assert any(
                    "Success: Dropped 1 matching nodes (force=True)" in str(args)
                    for args, kwargs in mock_print.call_args_list
                )

def test_cli_drop_matcher_no_match(tmp_path):
    input_content = [
        '!1 = !DIFile(filename: "test.c", directory: "/tmp")'
    ]
    input_file = tmp_path / "input_no_match.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch("builtins.input", side_effect=['drop basic_type()', "exit"]):
            with patch("builtins.print") as mock_print:
                cli.main()
                assert any(
                    "0 matches found." in str(args)
                    for args, kwargs in mock_print.call_args_list
                )


def test_unparse_overwrite(tmp_path):
    input_content = [
        '!0 = !{!"original"}'
    ]
    input_file = tmp_path / "to_overwrite.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    # Mock sys.argv to point to input.ll
    with patch("sys.argv", ["dimeta", str(input_file)]):
        # drop the node, then unparse -o, then exit
        with patch("builtins.input", side_effect=["drop !0", "unparse -o", "exit"]):
            with patch("builtins.print"):
                cli.main()

    # Check if input file was overwritten and is now empty because
    # the only node was dropped.
    # Actually, drop !0 will leave IR lines if any, but here there are none.
    # IRManager.save_file writes ir_lines then metadata.
    output_text = input_file.read_text().strip()
    assert output_text == ""

def test_unparse_overwrite_long_flag(tmp_path):
    input_content = [
        '!0 = !{!"original"}'
    ]
    input_file = tmp_path / "to_overwrite_long.ll"
    input_file.write_text("\n".join(input_content) + "\n")

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch("builtins.input", side_effect=["unparse --overwrite", "exit"]):
            with patch("builtins.print"):
                cli.main()

    output_text = input_file.read_text().strip()
    assert output_text == '!0 = !{!"original"}'

def test_unparse_overwrite_error_with_payload(tmp_path):
    input_file = tmp_path / "test.ll"
    input_file.write_text("!0 = !{}\n")

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch("builtins.input", side_effect=["unparse -o other.ll", "exit"]):
            with patch("builtins.print") as mock_print:
                cli.main()
                assert any(
                    (
                        "Error: Cannot provide a filename when using "
                        "--overwrite."
                    ) in str(args)
                    for args, kwargs in mock_print.call_args_list
                )


def test_diff_default_viewer(tmp_path):
    input_file = tmp_path / "input_diff.ll"
    input_file.write_text('!0 = !{!"x"}\n')

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch("builtins.input", side_effect=["diff", "exit"]):
            with patch("tempfile.gettempdir", return_value=str(tmp_path)):
                with patch("subprocess.run") as mock_run:
                    cli.main()

    assert mock_run.call_count == 1
    cmd = mock_run.call_args.args[0]
    assert cmd[0] == "meld"
    assert cmd[1] == str(input_file)
    assert cmd[2].startswith(str(tmp_path / "dimeta-query-tmp-input_diff-"))
    assert cmd[2].endswith(".ll")
    assert not os.path.exists(cmd[2])


def test_diff_custom_viewer(tmp_path):
    input_file = tmp_path / "input_diff_custom.ll"
    input_file.write_text('!0 = !{!"x"}\n')

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch("builtins.input", side_effect=["diff code --wait", "exit"]):
            with patch("tempfile.gettempdir", return_value=str(tmp_path)):
                with patch("subprocess.run") as mock_run:
                    cli.main()

    assert mock_run.call_count == 1
    cmd = mock_run.call_args.args[0]
    assert cmd[0] == "code"
    assert cmd[1] == "--wait"
    assert cmd[2] == str(input_file)
    assert cmd[3].startswith(str(tmp_path / "dimeta-query-tmp-input_diff_custom-"))
    assert cmd[3].endswith(".ll")
    assert not os.path.exists(cmd[3])


def test_diff_viewer_not_found(tmp_path):
    input_file = tmp_path / "input_diff_missing.ll"
    input_file.write_text('!0 = !{!"x"}\n')

    with patch("sys.argv", ["dimeta", str(input_file)]):
        with patch("builtins.input", side_effect=["diff", "exit"]):
            with patch("tempfile.gettempdir", return_value=str(tmp_path)):
                with patch("subprocess.run", side_effect=FileNotFoundError):
                    with patch("builtins.print") as mock_print:
                        cli.main()
                        assert any(
                            "Diff Error: Viewer 'meld' not found." in str(args)
                            for args, kwargs in mock_print.call_args_list
                        )
