"""Smoke tests for the Textual TUI front-end.

These tests are skipped automatically if the optional ``[tui]`` extra is
not installed (e.g. CI runs without it). They use Textual's ``Pilot``
harness via ``App.run_test()`` to drive the app without a real terminal.
"""

from __future__ import annotations

import pytest

pytest.importorskip("textual")
pytest.importorskip("textual_diff_view")

from dimeta_query.cli import setup_sandbox_globals  # noqa: E402
from dimeta_query.history import HistoryManager  # noqa: E402
from dimeta_query.ir import IRManager  # noqa: E402
from dimeta_query.tui import DimetaApp  # noqa: E402

SAMPLE_IR = (
    'define i32 @main() {\n'
    'entry:\n'
    '  ret i32 0\n'
    '}\n'
    '!1 = !DIBasicType(name: "int", size: 32, encoding: DW_ATE_signed)\n'
    '!2 = !DIFile(filename: "test.c", directory: "/tmp")\n'
)


def _build_app(tmp_path) -> tuple[DimetaApp, str]:
    ll_file = tmp_path / "smoke.ll"
    ll_file.write_text(SAMPLE_IR)
    manager = IRManager()
    manager.parse_file(str(ll_file))
    history = HistoryManager()
    sandbox = setup_sandbox_globals()
    app = DimetaApp(manager, history, sandbox, str(ll_file))
    return app, str(ll_file)


async def _submit(pilot, text: str) -> None:
    """Type a command into the input field and press Enter."""
    from textual.widgets import Input

    input_widget = pilot.app.query_one("#command-input", Input)
    input_widget.value = text
    input_widget.focus()
    await pilot.press("enter")
    await pilot.pause()


def _results_text(app: DimetaApp) -> str:
    """Return the text currently displayed in the results TextArea."""
    from textual.widgets import TextArea

    ta = app.query_one("#results-view", TextArea)
    return ta.text


@pytest.mark.asyncio
async def test_tui_mounts(tmp_path):
    app, _ = _build_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Source pane mounted with the (non-metadata) IR lines.
        from textual.widgets import TextArea

        ta = app.query_one("#source-view", TextArea)
        assert "define i32 @main" in ta.text
        # Subtitle reflects node count.
        assert "2 nodes" in app.sub_title


@pytest.mark.asyncio
async def test_tui_match_command(tmp_path):
    app, _ = _build_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _submit(pilot, 'm basic_type(has_name("int"))')
        text = _results_text(app)
        assert "Total matches: 1" in text


@pytest.mark.asyncio
async def test_tui_help_command(tmp_path):
    app, _ = _build_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _submit(pilot, "help")
        text = _results_text(app)
        assert "Available Commands" in text


@pytest.mark.asyncio
async def test_tui_drop_then_undo(tmp_path):
    app, _ = _build_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert len(app.manager.node_map) == 2

        await _submit(pilot, "drop !1")
        assert "1" not in app.manager.node_map
        assert len(app.manager.node_map) == 1

        await _submit(pilot, "undo")
        assert "1" in app.manager.node_map
        assert len(app.manager.node_map) == 2


@pytest.mark.asyncio
async def test_tui_inline_diff_mounts_widget(tmp_path):
    from textual_diff_view import DiffView

    app, _ = _build_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Mutate so the diff is non-trivial.
        await _submit(pilot, "drop !2")
        await _submit(pilot, "diff")
        from textual.containers import VerticalScroll

        container = app.query_one("#results-container", VerticalScroll)
        assert len(container.query(DiffView)) == 1


@pytest.mark.asyncio
async def test_tui_source_view_shows_and_refreshes_metadata(tmp_path):
    from textual.widgets import TextArea

    app, _ = _build_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        ta = app.query_one("#source-view", TextArea)

        # Startup: both IR body and metadata definitions visible.
        assert "define i32 @main" in ta.text
        assert "!DIBasicType" in ta.text
        assert "!DIFile" in ta.text

        # Drop the DIBasicType node; it should disappear from the source view.
        await _submit(pilot, "drop !1")
        assert "!DIBasicType" not in ta.text
        assert "!DIFile" in ta.text
        assert "define i32 @main" in ta.text

        # Undo restores it.
        await _submit(pilot, "undo")
        assert "!DIBasicType" in ta.text


@pytest.mark.asyncio
async def test_tui_unknown_command(tmp_path):
    app, _ = _build_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _submit(pilot, "bogus-command")
        text = _results_text(app)
        assert "Unknown command" in text


@pytest.mark.asyncio
async def test_tui_source_view_enables_llvm_highlighting(tmp_path):
    pytest.importorskip("tree_sitter_llvm")
    from textual.widgets import TextArea

    app, _ = _build_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        ta = app.query_one("#source-view", TextArea)
        assert "llvm" in ta._languages
        assert ta.language == "llvm"


def test_llvm_highlight_query_compiles_and_includes_metadata_captures():
    """The shipped llvm-highlights.scm must compile under tree-sitter and
    include the dimeta-query metadata extensions."""
    pytest.importorskip("tree_sitter_llvm")
    import warnings

    import tree_sitter_llvm
    from tree_sitter import Language, Parser, Query, QueryCursor

    from dimeta_query._highlight import load_llvm_language_and_query

    result = load_llvm_language_and_query()
    assert result is not None
    lang, query_src = result
    # If the .scm has syntax errors or unknown patterns, this raises.
    query = Query(lang, query_src)
    assert query.pattern_count > 30  # upstream has 37; we add ~9

    # Sanity-check that key extension scopes appear in the file.
    assert "@type.builtin" in query_src
    assert "@yaml.field" in query_src
    assert "@constant.builtin" in query_src
    assert "DW_" in query_src
    assert "DIFlag" in query_src

    # Functional check: parse a small snippet and confirm the metadata
    # captures actually fire on the right tokens.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        parser = Parser(Language(tree_sitter_llvm.language()))
    snippet = (
        b'!0 = !DICompileUnit(language: DW_LANG_C99, '
        b'emissionKind: FullDebug, flags: DIFlagPrototyped)\n'
        b'!1 = !{!0}\n'
        b'define void @f() !dbg !0 { ret void }\n'
    )
    tree = parser.parse(snippet)
    cur = QueryCursor(query)
    captures: dict[str, set[str]] = {}
    for name, nodes in cur.captures(tree.root_node).items():
        captures.setdefault(name, set()).update(n.text.decode() for n in nodes)

    assert "!DICompileUnit" in captures.get("type.builtin", set())
    assert "DW_LANG_C99" in captures.get("constant.builtin", set())
    assert "FullDebug" in captures.get("constant.builtin", set())
    assert "DIFlagPrototyped" in captures.get("constant.builtin", set())
    assert "language" in captures.get("yaml.field", set())
    assert "emissionKind" in captures.get("yaml.field", set())
    assert "!dbg" in captures.get("tag", set())
    # `!0` appears both as global_metadata LHS (=> @tag) and as inner ref
    # (=> @number). Both captures fire; Textual's renderer picks one.
    assert "!0" in captures.get("tag", set())
    assert "!0" in captures.get("number", set())


@pytest.mark.asyncio
async def test_tui_works_without_llvm_highlighting(tmp_path, monkeypatch):
    from textual.widgets import TextArea

    monkeypatch.setattr(
        "dimeta_query.tui.load_llvm_language_and_query",
        lambda: None,
    )

    app, _ = _build_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        ta = app.query_one("#source-view", TextArea)
        assert ta.language is None
        assert "!DIBasicType" in ta.text


def test_highlight_llvm_to_content_returns_spans():
    """Content has tree-sitter-derived spans for metadata tokens."""
    pytest.importorskip("tree_sitter_llvm")
    from dimeta_query._highlight import highlight_llvm_to_content

    text = (
        '!0 = !DICompileUnit(language: DW_LANG_C99, file: !1, '
        'emissionKind: FullDebug)\n'
        '!1 = !DIFile(filename: "test.c")\n'
    )
    content = highlight_llvm_to_content(text)
    assert content.plain == text
    assert len(content.spans) > 0

    # Build a lookup from (start,end) -> style for assertions.
    by_range = {(s.start, s.end): s.style for s in content.spans}

    # `!DICompileUnit` runs from byte 5 to 19.
    di_start = text.index("!DICompileUnit")
    di_end = di_start + len("!DICompileUnit")
    assert by_range.get((di_start, di_end)) == "$text-primary bold"

    # DWARF constant.
    dw_start = text.index("DW_LANG_C99")
    dw_end = dw_start + len("DW_LANG_C99")
    assert by_range.get((dw_start, dw_end)) == "bold $text-success 80%"

    # YAML field (key) `emissionKind`.
    key_start = text.index("emissionKind")
    key_end = key_start + len("emissionKind")
    assert by_range.get((key_start, key_end)) == "$text-accent bold"

    # String literal.
    str_start = text.index('"test.c"')
    str_end = str_start + len('"test.c"')
    assert by_range.get((str_start, str_end)) == "$text-success"


def test_highlight_llvm_to_content_ascii_tree_prefix():
    """Tree-sitter is error-tolerant: prefixed lines still highlight."""
    pytest.importorskip("tree_sitter_llvm")
    from dimeta_query._highlight import highlight_llvm_to_content

    text = (
        '!2 = !DICompileUnit(language: DW_LANG_C99)\n'
        ' \u2514\u2500 !0 = !DIFile(filename: "test.c")\n'
    )
    content = highlight_llvm_to_content(text)
    # Despite the box-drawing prefix, the kind name on line 2 must still
    # be captured. Textual Spans are character-indexed; if the highlighter
    # mistakenly used tree-sitter's byte offsets, the span here would be
    # shifted right by 4 (two 3-byte chars contributing +2 bytes each).
    di_start = text.index("!DIFile")
    di_end = di_start + len("!DIFile")
    matched = any(
        s.start == di_start and s.end == di_end and s.style == "$text-primary bold"
        for s in content.spans
    )
    assert matched, f"!DIFile not highlighted; spans={content.spans!r}"

    # Contract check: for every span, slicing the original text by
    # (span.start, span.end) yields the expected token text.
    for s in content.spans:
        sliced = text[s.start : s.end]
        assert sliced.strip(), (
            f"span {s} slices empty/whitespace from text; off-by-bytes regression?"
        )


def test_highlight_llvm_to_content_no_dep_returns_plain(monkeypatch):
    """Without tree-sitter the helper returns plain Content."""
    monkeypatch.setattr(
        "dimeta_query._highlight.load_llvm_language_and_query",
        lambda: None,
    )
    # Reset the module cache so the patched loader is consulted.
    monkeypatch.setattr("dimeta_query._highlight._QUERY_CACHE", None)

    from dimeta_query._highlight import highlight_llvm_to_content

    text = "!0 = !DIFile(filename: \"x.c\")\n"
    content = highlight_llvm_to_content(text)
    assert content.plain == text
    assert content.spans == []


@pytest.mark.asyncio
async def test_tui_show_text_uses_highlighter(tmp_path):
    """The `p` command loads its output into the results TextArea, which is
    configured with the LLVM tree-sitter language."""
    pytest.importorskip("tree_sitter_llvm")
    from textual.widgets import TextArea

    app, _ = _build_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _submit(pilot, "p !1")
        ta = app.query_one("#results-view", TextArea)
        assert ta.language == "llvm"
        assert "!DIBasicType" in ta.text
        # TextArea is visible (not hidden by a diff view) and read-only.
        assert ta.display is True
        assert ta.read_only is True


@pytest.mark.asyncio
async def test_tui_diff_uses_llvm_highlight(tmp_path):
    """LlvmDiffView produces content lines with our tree-sitter palette."""
    pytest.importorskip("tree_sitter_llvm")
    from dimeta_query.tui import LlvmDiffView

    app, _ = _build_app(tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        await _submit(pilot, "drop !2")
        await _submit(pilot, "diff")
        widgets = list(app.query(LlvmDiffView))
        assert len(widgets) == 1
        dv = widgets[0]
        lines_a, lines_b = dv.highlighted_code_lines
        # At least one rendered line on either side must carry our
        # signature LLVM palette style.
        all_styles = {
            s.style
            for line in lines_a + lines_b
            for s in line.spans
        }
        assert "$text-primary bold" in all_styles, (
            f"LLVM palette not present in diff content; got styles={all_styles!r}"
        )
