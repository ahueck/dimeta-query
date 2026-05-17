"""Textual-based TUI for dimeta-query.

The TUI is an alternative front-end to the same command set exposed by the
classic REPL in ``cli.py``. All actual command logic is delegated to the
existing ``_handle_*`` helpers in ``cli.py`` and their stdout output is
captured into the results pane.

This module is imported lazily by ``cli.main`` so that users without the
``[tui]`` extra installed can still use the project (``pip install
dimeta-query[tui]`` enables this module).
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import tempfile
from collections import deque
from typing import TYPE_CHECKING, Any, Deque, Dict, List, Optional, cast

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.content import Content
from textual.events import Click, MouseDown, MouseMove, MouseUp
from textual.widget import Widget
from textual.widgets import Footer, Header, Input, TextArea
from textual_diff_view import DiffView

from . import cli as cli_module
from ._highlight import highlight_llvm_to_content, load_llvm_language_and_query
from .history import HistoryManager
from .ir import IRManager
from .unparser import DanglingReferenceError

if TYPE_CHECKING:
    from textual.document._document import Document

# Commands that mutate IRManager state and therefore require a source-view refresh.
_MUTATING_COMMANDS = frozenset({"drop", "sweep", "undo", "redo"})

# Regex for metadata references like !1 or !42.
_METADATA_REF_RE = re.compile(r"!\d+")


class LlvmDiffView(DiffView):
    """DiffView that highlights LLVM IR via our tree-sitter query.

    Falls back to upstream Pygments-based highlighting for other
    languages (none in practice since this widget is only used for
    ``.ll`` content, but the fallback keeps it well-behaved).
    """

    @classmethod
    def highlight(
        cls,
        code: str,
        path: str,
        language: str,
        ansi: bool = False,
        dark: bool = False,
    ) -> Content:
        if language == "llvm" or (path and path.endswith(".ll")):
            return highlight_llvm_to_content(code)
        return super().highlight(code, path, language, ansi=ansi, dark=dark)


class DraggableSplitter(Widget):
    """A 1-line horizontal splitter the user can drag to resize the pane above."""

    DEFAULT_CSS = """
    DraggableSplitter {
        height: 1;
        width: 100%;
        background: #2b2b2b;
        color: #888888;
        content-align: center middle;
    }
    DraggableSplitter:hover {
        background: #4a4a4a;
        color: #ffffff;
    }
    """

    def __init__(self, target_id: str) -> None:
        super().__init__()
        self.target_id = target_id
        self._dragging = False

    def render(self) -> str:
        return "═══════════════"

    def on_mouse_down(self, event: MouseDown) -> None:
        self.capture_mouse()
        self._dragging = True

    def on_mouse_up(self, event: MouseUp) -> None:
        self.release_mouse()
        self._dragging = False

    def on_mouse_move(self, event: MouseMove) -> None:
        if not self._dragging:
            return
        target_pane = self.app.query_one(f"#{self.target_id}")
        min_height = 2
        max_height = max(min_height, self.app.size.height - 8)
        new_height = event.screen_y - 1
        target_pane.styles.height = max(min_height, min(new_height, max_height))


class DimetaApp(App[None]):
    """Interactive Textual UI for exploring and mutating LLVM IR metadata."""

    CSS = """
    Screen {
        layout: vertical;
    }

    #source-view {
        height: 3fr;
        border: round #325b84;
    }

    #results-container {
        height: 1fr;
        min-height: 5;
        border: round #119283;
    }

    #results-view {
        height: 1fr;
        border: none;
        padding: 0;
    }

    /* Suppress the focus border on the read-only results view. */
    #results-view:focus {
        border: none;
    }

    #command-input {
        height: 3;
        border: round #4a4a4a;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear_results", "Clear", show=True),
        Binding("ctrl+z", "undo", "Undo", show=True),
        Binding("ctrl+y", "redo", "Redo", show=True),
        Binding("ctrl+s", "save_inplace", "Save", show=True),
        Binding("f1", "show_help", "Help", show=True),
        Binding("n", "source_search_next", "Next", show=False),
        Binding("N", "source_search_prev", "Prev", show=False),
        Binding("/", "start_source_search", "Search", show=False),
        Binding(":", "focus_command", "Command", show=False),
    ]

    def __init__(
        self,
        manager: IRManager,
        history: HistoryManager,
        sandbox_globals: Dict[str, Any],
        opened_file: str,
    ) -> None:
        super().__init__()
        self.manager = manager
        self.history = history
        self.sandbox_globals = sandbox_globals
        self.opened_file = opened_file

        # User-typed command history for Up/Down recall in the input.
        self._cmd_history: Deque[str] = deque(maxlen=200)
        self._cmd_history_idx: Optional[int] = None
        self._cmd_history_draft: str = ""

        # Temp files mounted into DiffView; cleaned up on next command/unmount.
        self._pending_temp_files: List[str] = []

        # TUI-only source search state.
        self._source_search_query: Optional[str] = None
        self._source_search_last_idx: Optional[int] = None

    # ------------------------------------------------------------------
    # Compose / layout
    # ------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)

        source_text = self._render_source_text()
        yield self._make_llvm_textarea(
            source_text,
            id="source-view",
            show_line_numbers=True,
        )

        yield DraggableSplitter(target_id="source-view")

        with VerticalScroll(
            id="results-container",
            can_focus=False,
            can_focus_children=True,
        ):
            yield self._make_llvm_textarea(
                "Welcome to dimeta-query TUI. "
                "Press F1 for help, Ctrl+Q to quit.",
                id="results-view",
                show_line_numbers=False,
                show_cursor=True,
                can_focus=True,
                highlight_cursor_line=False,
                language=None,
            )

        yield Input(placeholder="dimeta-query> ", id="command-input")
        yield Footer()

    @staticmethod
    def _make_llvm_textarea(
        text: str,
        *,
        id: str,
        show_line_numbers: bool,
        show_cursor: bool = True,
        can_focus: bool = True,
        highlight_cursor_line: bool = True,
        language: Optional[str] = "llvm",
    ) -> TextArea:
        """Build a read-only TextArea with optional highlighting attached."""
        text_area = TextArea(
            text,
            read_only=True,
            show_line_numbers=show_line_numbers,
            show_cursor=show_cursor,
            highlight_cursor_line=highlight_cursor_line,
            id=id,
        )
        text_area.can_focus = can_focus

        # Always try to register the LLVM highlighter if available, so that
        # we can toggle it on later even if starting as plain text.
        llvm_registered = False
        llvm = load_llvm_language_and_query()
        if llvm is not None:
            lang, query = llvm
            try:
                text_area.register_language("llvm", lang, query)
                llvm_registered = True
            except Exception:
                pass

        if language == "llvm":
            if llvm_registered:
                text_area.language = "llvm"
        elif language is not None:
            text_area.language = language

        return text_area

    def on_mount(self) -> None:
        self._refresh_subtitle()
        try:
            self.query_one("#command-input", Input).focus()
        except Exception:
            pass

    async def on_click(self, event: Click) -> None:
        """Jump to metadata definition on click in the source view."""
        try:
            source_text_area = self.query_one("#source-view", TextArea)
        except Exception:
            return

        # Only handle left-clicks on the source TextArea.
        is_source = (event.widget is not source_text_area and
                     event.control is not source_text_area)
        if event.button != 1 or is_source:
            return

        row, col = source_text_area.get_target_document_location(event)
        try:
            line = source_text_area.document.get_line(row)
        except Exception:
            return

        # Identify which !N (if any) was clicked.
        clicked_ref: Optional[str] = None
        for match in _METADATA_REF_RE.finditer(line):
            if match.start() <= col < match.end():
                clicked_ref = match.group()
                break

        if clicked_ref is None:
            return

        # Find the definition line for this ID.
        ref_id = clicked_ref[1:]
        # Use (?m) for multiline search and match !N at start of line.
        pattern = rf"(?m)^!{re.escape(ref_id)}\s*="
        def_match = re.search(pattern, source_text_area.text)
        if def_match is None:
            msg = f"No definition found for {clicked_ref}."
            await self._show_text(msg, language=None)
            return

        # Select the definition token and jump there.
        doc = cast("Document", source_text_area.document)
        start_loc = doc.get_location_from_index(def_match.start())
        end_loc = doc.get_location_from_index(def_match.start() + len(clicked_ref))

        source_text_area.move_cursor(start_loc)
        source_text_area.move_cursor(end_loc, select=True, center=True)
        source_text_area.focus()
        event.stop()

    def _refresh_subtitle(self) -> None:
        self.sub_title = (
            f"{os.path.basename(self.opened_file)} — "
            f"{len(self.manager.node_map)} nodes"
        )

    def _render_source_text(self) -> str:
        """Build the source-view contents: IR lines + serialized metadata.

        Matches IRManager.save_file's serialization so the source view
        previews what `unparse` would write.
        """
        return self.manager.unparse()

    async def _refresh_source_view(self) -> None:
        """Reload source pane from manager state, preserving cursor/scroll."""
        self._source_search_query = None
        self._source_search_last_idx = None
        try:
            ta = self.query_one("#source-view", TextArea)
        except Exception:
            return

        prev_cursor = ta.cursor_location
        prev_scroll = ta.scroll_offset

        new_text = self._render_source_text()
        ta.load_text(new_text)

        # Clamp cursor to new document bounds.
        line_count = ta.document.line_count
        if line_count > 0:
            row = min(prev_cursor[0], line_count - 1)
            line_text = ta.document.get_line(row)
            col = min(prev_cursor[1], len(line_text))
            try:
                ta.move_cursor((row, col))
            except Exception:
                pass

        # Restore scroll; Textual clamps if it exceeds new content height.
        try:
            ta.scroll_to(x=prev_scroll.x, y=prev_scroll.y, animate=False)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Bindings & Actions
    # ------------------------------------------------------------------
    async def action_source_search_next(self) -> None:
        if self._source_search_query:
            await self._run_source_search(self._source_search_query, forward=True)

    async def action_source_search_prev(self) -> None:
        if self._source_search_query:
            await self._run_source_search(self._source_search_query, forward=False)

    async def action_start_source_search(self) -> None:
        input_widget = self.query_one("#command-input", Input)
        input_widget.value = "/"
        input_widget.focus()
        input_widget.cursor_position = 1

    async def action_focus_command(self) -> None:
        self.query_one("#command-input", Input).focus()

    async def action_quit(self) -> None:
        self._cleanup_temp_files()
        self.exit()

    async def action_clear_results(self) -> None:
        await self._clear_results()

    async def action_undo(self) -> None:
        await self._run_captured("undo", {}, "")

    async def action_redo(self) -> None:
        await self._run_captured("redo", {}, "")

    async def action_save_inplace(self) -> None:
        flags = self._default_flags()
        flags["overwrite"] = True
        await self._run_captured("unparse", flags, "")

    async def action_show_help(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cli_module.print_help()
        await self._show_text(buf.getvalue() or "(no help)", language=None)
        # Append TUI-only commands to the help output.
        ta = self.query_one("#results-view", TextArea)
        tui_help = (
            "\nTUI-only Commands:\n"
            "  /<text>          Search source pane\n"
            "  n                Jump to next match (when source is focused)\n"
            "  N                Jump to previous match (when source is focused)\n"
            "  :                Focus command input\n"
        )
        ta.load_text(ta.text + tui_help)
        ta.scroll_end(animate=False)

    # ------------------------------------------------------------------
    # Command history (Up/Down inside the Input)
    # ------------------------------------------------------------------
    def on_key(self, event: events.Key) -> None:
        try:
            input_widget = self.query_one("#command-input", Input)
        except Exception:
            return
        if not input_widget.has_focus:
            return

        if event.key == "up":
            if not self._cmd_history:
                return
            if self._cmd_history_idx is None:
                self._cmd_history_draft = input_widget.value
                self._cmd_history_idx = len(self._cmd_history) - 1
            elif self._cmd_history_idx > 0:
                self._cmd_history_idx -= 1
            input_widget.value = self._cmd_history[self._cmd_history_idx]
            input_widget.cursor_position = len(input_widget.value)
            event.stop()
        elif event.key == "down":
            if self._cmd_history_idx is None:
                return
            if self._cmd_history_idx < len(self._cmd_history) - 1:
                self._cmd_history_idx += 1
                input_widget.value = self._cmd_history[self._cmd_history_idx]
            else:
                self._cmd_history_idx = None
                input_widget.value = self._cmd_history_draft
            input_widget.cursor_position = len(input_widget.value)
            event.stop()

    # ------------------------------------------------------------------
    # Command dispatch
    # ------------------------------------------------------------------
    async def on_input_submitted(self, event: Input.Submitted) -> None:
        line = event.value.strip()
        event.input.value = ""
        self._cmd_history_idx = None
        self._cmd_history_draft = ""
        if not line:
            return

        if line.startswith("/"):
            self._cmd_history.append(line)
            await self._run_source_search(line[1:])
            return

        self._cmd_history.append(line)

        cmd, flags, payload = cli_module.parse_repl_line(line)

        if cmd in ("exit", "quit"):
            self._cleanup_temp_files()
            self.exit()
            return

        if cmd == "help":
            await self.action_show_help()
            return

        if cmd == "diff" and not payload:
            await self._run_inline_diff()
            return

        await self._run_captured(cmd, flags, payload)

    async def _run_source_search(self, query: str, forward: bool = True) -> None:
        """Find the needle in the source pane, selecting the match."""
        if not query:
            return

        try:
            ta = self.query_one("#source-view", TextArea)
        except Exception:
            return

        text = ta.text
        if not text:
            return

        # Use TextArea/Document APIs to determine search start.
        doc = cast("Document", ta.document)
        if (
            query == self._source_search_query
            and self._source_search_last_idx is not None
        ):
            # Repeat search: move past current match.
            start_offset = self._source_search_last_idx + (1 if forward else -1)
        else:
            # New search: start from cursor.
            start_offset = doc.get_index_from_location(ta.cursor_location)

        if forward:
            idx = text.find(query, start_offset)
            if idx == -1:
                idx = text.find(query, 0)  # Wrap
        else:
            idx = text.rfind(query, 0, max(0, start_offset))
            if idx == -1:
                idx = text.rfind(query)  # Wrap

        if idx == -1:
            await self._show_text(f'No match for "{query}".', language=None)
            self._source_search_query = None
            self._source_search_last_idx = None
            return

        self._source_search_query = query
        self._source_search_last_idx = idx

        target_loc = doc.get_location_from_index(idx)
        end_loc = doc.get_location_from_index(idx + len(query))

        ta.move_cursor(target_loc)
        ta.move_cursor(end_loc, select=True, center=True)

        await self._show_text(
            f'Found "{query}" at line {target_loc[0] + 1}, column {target_loc[1]}.',
            language=None,
        )
        # Shift focus to source for n/N navigation.
        ta.focus()

    async def _run_captured(
        self, cmd: str, flags: Dict[str, Any], payload: str
    ) -> None:
        """Dispatch a command through cli.dispatch_command, capturing stdout."""
        # Ensure missing flag keys exist so dispatch_command can index them.
        merged_flags = self._default_flags()
        merged_flags.update(flags or {})

        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                recognized = cli_module.dispatch_command(
                    cmd,
                    merged_flags,
                    payload,
                    self.manager,
                    self.history,
                    self.sandbox_globals,
                    self.opened_file,
                )
                if not recognized:
                    print(f"Unknown command: '{cmd}'. Press F1 for help.")
        except Exception as e:  # safety net — handlers normally swallow errors
            print(f"Unexpected error: {e}", file=buf)

        output = buf.getvalue() or "(no output)"
        # Selectively disable highlighting for non-IR output (errors, status).
        language: Optional[str] = "llvm"
        if not recognized or any(
            output.startswith(p)
            for p in (
                "Error:",
                "Query Error:",
                "Execution Error:",
                "Success:",
                "Undone:",
                "Redone:",
            )
        ):
            language = None

        await self._show_text(output, language=language)
        self._refresh_subtitle()
        if cmd in _MUTATING_COMMANDS:
            await self._refresh_source_view()

    async def _run_inline_diff(self) -> None:
        """Render an inline diff of the on-disk file vs the in-memory graph."""
        self._cleanup_temp_files()

        opened_basename = os.path.basename(self.opened_file)
        opened_stem, _ = os.path.splitext(opened_basename)
        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                delete=False,
                prefix=f"dimeta-query-tmp-{opened_stem}-",
                suffix=".ll",
                dir=tempfile.gettempdir(),
            ) as tmp:
                tmp_path = tmp.name

            self._pending_temp_files.append(tmp_path)
            self.manager.save_file(tmp_path)

            with open(self.opened_file, "r") as f:
                code_original = f.read()
            with open(tmp_path, "r") as f:
                code_modified = f.read()
        except DanglingReferenceError as e:
            await self._show_text(f"Diff Error: {e}", language=None)
            return
        except Exception as e:
            await self._show_text(f"Diff Error: {e}", language=None)
            return

        diff_widget = LlvmDiffView(
            path_original=self.opened_file,
            path_modified=tmp_path or "modified.ll",
            code_original=code_original,
            code_modified=code_modified,
            auto_split=True,
            annotations=True,
            wrap=True,
        )

        # Hide the persistent results TextArea and mount the diff widget
        # alongside it in the VerticalScroll. Calling _clear_results would
        # remove any previous DiffView; do that first.
        await self._remove_diff_widgets()
        result_text_area = self.query_one("#results-view", TextArea)
        result_text_area.display = False
        container = self.query_one("#results-container", VerticalScroll)
        await container.mount(diff_widget)

    # ------------------------------------------------------------------
    # Results pane helpers
    # ------------------------------------------------------------------
    async def _remove_diff_widgets(self) -> None:
        """Tear down any LlvmDiffView previously mounted in the results pane."""
        container = self.query_one("#results-container", VerticalScroll)
        for w in list(container.query(DiffView)):
            await w.remove()

    async def _clear_results(self) -> None:
        await self._remove_diff_widgets()
        result_text_area = self.query_one("#results-view", TextArea)
        result_text_area.display = True
        result_text_area.load_text("")
        result_text_area.scroll_home(animate=False)

    async def _show_text(self, text: str, language: Optional[str] = "llvm") -> None:
        await self._remove_diff_widgets()
        result_text_area = self.query_one("#results-view", TextArea)
        result_text_area.display = True
        result_text_area.language = language
        # Textual's TextArea applies tree-sitter LLVM highlighting via its
        # registered language; we just load the text.
        result_text_area.load_text(text)
        result_text_area.scroll_home(animate=False)

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------
    @staticmethod
    def _default_flags() -> Dict[str, Any]:
        return {
            "verbose": False,
            "depth": -1,
            "force": False,
            "summary": False,
            "flat": False,
            "all": False,
            "reduce": False,
            "overwrite": False,
        }

    def _cleanup_temp_files(self) -> None:
        for path in self._pending_temp_files:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        self._pending_temp_files.clear()

    def on_unmount(self) -> None:
        self._cleanup_temp_files()


def run_tui(
    manager: IRManager,
    history: HistoryManager,
    sandbox_globals: Dict[str, Any],
    opened_file: str,
) -> None:
    """Launch the Textual TUI for the given pre-loaded IR state."""
    app = DimetaApp(manager, history, sandbox_globals, opened_file)
    app.run()
