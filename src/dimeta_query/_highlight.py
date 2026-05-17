"""Optional LLVM IR syntax-highlighting support for the TUI.

This module is imported by ``tui.py`` and isolates the tree-sitter LLVM
dependency. If ``tree-sitter-llvm`` (and therefore ``tree-sitter``) is not
available, or the bundled highlight query cannot be read, the loaders
return ``None`` and the TUI falls back to plain text everywhere.

The highlight query is read from ``llvm-highlights.scm`` shipped inside
this package. The file starts as a copy of the upstream
``tree_sitter_llvm`` query and is extended with additional captures for
LLVM debug-info metadata (see the file for details).

Two entry points are exposed:

* :func:`load_llvm_language_and_query` returns ``(Language, query_text)``
  for the Textual ``TextArea`` syntax highlighter, which compiles the
  query itself when ``language="llvm"`` is set on the widget.

* :func:`highlight_llvm_to_content` produces a Textual ``Content`` with
  pre-styled spans for *any* string of LLVM-ish text. This is used to
  highlight the results pane (``p``/``m`` output) and the diff view's
  per-line code, both of which take a ``Content`` rather than a live
  tree-sitter parse.
"""

from __future__ import annotations

import warnings
from importlib.resources import files
from typing import TYPE_CHECKING, Optional, Tuple, Union

from textual.content import Content, Span

if TYPE_CHECKING:
    from tree_sitter import Language
    from tree_sitter import Query as TSQuery


def load_llvm_language_and_query() -> Optional[Tuple["Language", str]]:
    """Return ``(Language, highlight_query)`` or ``None`` if unavailable.

    All failure modes (missing dependency, missing query file, broken
    binding) are swallowed and reported as ``None`` so the caller can
    degrade gracefully to a plain TextArea.
    """
    try:
        import tree_sitter_llvm
        from tree_sitter import Language
    except Exception:
        return None

    try:
        scm = (
            files("dimeta_query") / "llvm-highlights.scm"
        ).read_text(encoding="utf-8")
    except Exception:
        return None

    try:
        # tree_sitter_llvm.language() returns a PyCapsule encoded as int,
        # which Language() accepts but emits a DeprecationWarning. The
        # package exposes no alternative entry point as of 1.1.0.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            lang = Language(tree_sitter_llvm.language())
    except Exception:
        return None

    return lang, scm


# Mapping from tree-sitter capture names (as they appear in our extended
# llvm-highlights.scm) to Textual theme-variable styles. Variables resolve
# at render time so the highlights adapt to the active app theme.
#
# Palette intentionally mirrors textual.highlight.HighlightTheme.STYLES so
# diff-view output for LLVM looks consistent with Pygments output for
# other languages.
_CAPTURE_STYLES: dict[str, str] = {
    "type": "$text-primary",
    "type.builtin": "$text-primary bold",
    "keyword": "$text-accent",
    "keyword.function": "$text-accent",
    "keyword.operator": "$text-accent",
    "keyword.control": "$text-error",
    "keyword.control.return": "$text-error",
    "function": "$text-primary",
    "string": "$text-success",
    "cstring": "$text-success",
    "number": "$text-warning",
    "float": "$text-warning",
    "constant.numeric.integer": "$text-warning",
    "constant.numeric.float": "$text-warning",
    "constant.builtin": "bold $text-success 80%",
    "constant.builtin.boolean": "bold $text-success 80%",
    "comment": "$text 60%",
    "operator": "$text-secondary",
    "punctuation.bracket": "$text 80%",
    "punctuation.delimiter": "$text 80%",
    "variable": "$text-primary",
    "variable.parameter": "$text-primary",
    "label": "$text-warning",
    "constructor": "$text-accent",
    "tag": "$text-accent",
    "yaml.field": "$text-accent bold",
    # `error` and any unknown captures intentionally have no style so
    # they render in the base body style.
}


# Cached (Language, compiled Query) pair, or False if loading failed.
# Loaded lazily on first call to highlight_llvm_to_content.
_QUERY_CACHE: Union[Tuple["Language", "TSQuery"], bool, None] = None


def _get_cached_language_and_query() -> Optional[Tuple["Language", "TSQuery"]]:
    """Lazily load and compile the LLVM tree-sitter query, with caching."""
    global _QUERY_CACHE
    if _QUERY_CACHE is False:
        return None
    if _QUERY_CACHE is not None:
        # Already a (Language, Query) tuple.
        assert isinstance(_QUERY_CACHE, tuple)
        return _QUERY_CACHE

    loaded = load_llvm_language_and_query()
    if loaded is None:
        _QUERY_CACHE = False
        return None
    lang, query_src = loaded
    try:
        from tree_sitter import Query
    except Exception:
        _QUERY_CACHE = False
        return None
    try:
        query = Query(lang, query_src)
    except Exception:
        _QUERY_CACHE = False
        return None
    _QUERY_CACHE = (lang, query)
    return _QUERY_CACHE


def highlight_llvm_to_content(text: str) -> Content:
    """Return a Textual ``Content`` with tree-sitter LLVM spans applied.

    If the LLVM grammar / query cannot be loaded, returns a plain
    ``Content`` wrapping the original text (no spans). Tree-sitter is
    error-tolerant, so feeding non-LLVM text (e.g. help messages, error
    strings, ASCII-tree decorated metadata) is safe — anything the
    parser can't classify simply yields no captures and renders plain.
    """
    if not text:
        return Content(text)

    cached = _get_cached_language_and_query()
    if cached is None:
        return Content(text)
    lang, query = cached

    try:
        from tree_sitter import Parser, QueryCursor
    except Exception:
        return Content(text)

    try:
        parser = Parser(lang)
        tree = parser.parse(text.encode("utf-8"))
        cursor = QueryCursor(query)
        captures = cursor.captures(tree.root_node)
    except Exception:
        return Content(text)

    # Textual ``Span`` indices are *character* offsets, but tree-sitter
    # reports *byte* offsets. For pure-ASCII text these coincide; for
    # text containing multi-byte UTF-8 sequences (e.g. the box-drawing
    # characters from format_ascii_tree's tree prefixes) we need a
    # byte->char translation table or every span downstream of the first
    # multibyte char is misaligned.
    b2c = None if text.isascii() else _byte_to_char_index(text)

    spans: list[Span] = []
    for capture_name, nodes in captures.items():
        style = _CAPTURE_STYLES.get(capture_name)
        if style is None:
            continue
        for node in nodes:
            if b2c is None:
                start, end = node.start_byte, node.end_byte
            else:
                start, end = b2c[node.start_byte], b2c[node.end_byte]
            spans.append(Span(start, end, style))

    return Content(text, spans=spans)


def _byte_to_char_index(text: str) -> list[int]:
    """Return a list mapping UTF-8 byte offset -> character offset.

    ``result[byte_offset]`` yields the character offset within ``text``
    that contains the given byte. The list has length
    ``len(text.encode("utf-8")) + 1`` so that the end-of-text byte
    offset is also addressable.
    """
    mapping: list[int] = []
    for char_idx, ch in enumerate(text):
        mapping.extend([char_idx] * len(ch.encode("utf-8")))
    mapping.append(len(text))
    return mapping
