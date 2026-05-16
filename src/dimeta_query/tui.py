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
import tempfile
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.content import Content
from textual.events import MouseDown, MouseMove, MouseUp
from textual.widget import Widget
from textual.widgets import Footer, Header, Input, TextArea
from textual_diff_view import DiffView

from . import cli as cli_module
from ._highlight import highlight_llvm_to_content, load_llvm_language_and_query
from .history import HistoryManager
from .ir import IRManager
from .unparser import DanglingReferenceError

# Commands that mutate IRManager state and therefore require a source-view refresh.
_MUTATING_COMMANDS = frozenset({"drop", "sweep", "undo", "redo"})


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
        return "═══ Drag to Resize ═══"

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
        min_height = 3
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

        with VerticalScroll(id="results-container"):
            yield self._make_llvm_textarea(
                "Welcome to dimeta-query TUI. "
                "Press F1 for help, Ctrl+Q to quit.",
                id="results-view",
                show_line_numbers=False,
                show_cursor=False,
                can_focus=False,
                highlight_cursor_line=False,
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
    ) -> TextArea:
        """Build a read-only TextArea with LLVM tree-sitter highlighting attached."""
        text_area = TextArea(
            text,
            read_only=True,
            show_line_numbers=show_line_numbers,
            show_cursor=show_cursor,
            highlight_cursor_line=highlight_cursor_line,
            id=id,
        )
        text_area.can_focus = can_focus
        llvm = load_llvm_language_and_query()
        if llvm is not None:
            lang, query = llvm
            try:
                text_area.register_language("llvm", lang, query)
                text_area.language = "llvm"
            except Exception:
                # Highlighter failed to attach; fall back to plain text.
                pass
        return text_area

    def on_mount(self) -> None:
        self._refresh_subtitle()
        try:
            self.query_one("#command-input", Input).focus()
        except Exception:
            pass

    def _refresh_subtitle(self) -> None:
        self.sub_title = (
            f"{os.path.basename(self.opened_file)} — "
            f"{len(self.manager.node_map)} nodes"
        )

    @staticmethod
    def _metadata_sort_key(node_id: str) -> Any:
        """Mirror IRManager.save_file's sort: named IDs first, then numeric."""
        if node_id.isdigit():
            return (1, int(node_id))
        return (0, node_id)

    def _render_source_text(self) -> str:
        """Build the source-view contents: IR lines + serialized metadata.

        Matches IRManager.save_file's serialization so the source view
        previews what `unparse` would write. Nodes with empty raw_text
        (proxies, dropped-but-still-referenced) are skipped.
        """
        parts: List[str] = ["".join(self.manager.ir_lines)]
        sorted_ids = sorted(self.manager.node_map.keys(), key=self._metadata_sort_key)
        meta_lines = []
        for node_id in sorted_ids:
            node = self.manager.node_map[node_id]
            if node.raw_text:
                meta_lines.append(node.raw_text)
        if meta_lines:
            if parts[0] and not parts[0].endswith("\n"):
                parts.append("\n")
            parts.append("\n".join(meta_lines))
            parts.append("\n")
        return "".join(parts)

    async def _refresh_source_view(self) -> None:
        """Reload source pane from manager state, preserving cursor/scroll."""
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
    # Bindings
    # ------------------------------------------------------------------
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
        await self._show_text(buf.getvalue() or "(no help)")

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

        await self._show_text(buf.getvalue() or "(no output)")
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
            await self._show_text(f"Diff Error: {e}")
            return
        except Exception as e:
            await self._show_text(f"Diff Error: {e}")
            return

        diff_widget = LlvmDiffView(
            path_original=self.opened_file,
            path_modified=tmp_path or "modified.ll",
            code_original=code_original,
            code_modified=code_modified,
            auto_split=True,
            annotations=True,
        )

        # Hide the persistent results TextArea and mount the diff widget
        # alongside it in the VerticalScroll. Calling _clear_results would
        # remove any previous DiffView; do that first.
        await self._remove_diff_widgets()
        ta = self.query_one("#results-view", TextArea)
        ta.display = False
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
        ta = self.query_one("#results-view", TextArea)
        ta.display = True
        ta.load_text("")
        ta.scroll_home(animate=False)

    async def _show_text(self, text: str) -> None:
        await self._remove_diff_widgets()
        result_text_area = self.query_one("#results-view", TextArea)
        result_text_area.display = True
        # Textual's TextArea applies tree-sitter LLVM highlighting via its
        # registered language; we just load the text. Non-LLVM lines
        # (errors, help) yield no captures and render in the base style.
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
