import argparse
import importlib.util
import os
import shlex
import subprocess
import sys
import tempfile

if importlib.util.find_spec("readline"):
    import readline  # noqa: F401  # Enables arrow keys history and better input in the REPL
from typing import Any, Dict, Optional

from .formatter import format_ascii_tree, format_flat_list
from .graph_manager import drop_node
from .history import GraphSnapshot, HistoryManager
from .ir import IRManager

# Import all matchers and modifiers to inject into the sandbox
from .matchers import (
    basic_type,
    composite_type,
    derived_type,
    file_node,
    has_attr,
    has_base_type,
    has_child,
    has_element,
    has_flag,
    has_name,
    has_property,
    has_scope,
    has_tag,
    has_type,
    lexical_block,
    local_variable,
    node,
    subprogram,
    subrange,
)
from .modifiers import demangle, fuzzy
from .query import MatchResult, evaluate_query
from .repl import SecurityError, execute_safely
from .unparser import DanglingReferenceError, Unparser


def setup_sandbox_globals() -> Dict[str, Any]:
    """Returns a dictionary of all whitelisted functions allowed in the REPL."""
    return {
        "node": node,
        "local_variable": local_variable,
        "composite_type": composite_type,
        "derived_type": derived_type,
        "basic_type": basic_type,
        "subrange": subrange,
        "subprogram": subprogram,
        "file_node": file_node,
        "lexical_block": lexical_block,
        "has_name": has_name,
        "has_flag": has_flag,
        "has_type": has_type,
        "has_scope": has_scope,
        "has_element": has_element,
        "has_child": has_child,
        "has_base_type": has_base_type,
        "has_tag": has_tag,
        "has_attr": has_attr,
        "has_property": has_property,
        "fuzzy": fuzzy,
        "demangle": demangle
    }

def print_help() -> None:
    print("""
Available Commands:
  m [-v] [-n [level]] [-s] [-l] <query>
                   Evaluate a matcher query
                   (e.g., m composite_type(has_name("foo")))
                   -v, --verbose: Show more detailed tree output.
                   -n, --node-only [level]: Limit tree depth (default 0).
                   -s, --summary: Print only node names, no payloads.
                   -l, --list: Print as a flat, deduplicated list.
  p [-v] [-n [level]] [-s] [-l] <id>
                   Print a specific metadata node by ID (e.g., p !1, p 42)
                   -v, --verbose: Show more detailed tree output.
                   -n, --node-only [level]: Limit tree depth (default 0).
                   -s, --summary: Print only node names, no payloads.
                   -l, --list: Print as a flat, deduplicated list.
  drop [-f] <id|query>
                   Safely drop a node by ID or all nodes matching a query
                   (e.g., drop !42, drop node(has_name("test")))
                   Use -f or --force to force drop.
  sweep [-a] [-r]    Remove all metadata nodes not reachable from IR
                   -a, --all: Also discard unreferenced named metadata.
                   -r, --reduce: Reduce DIFile paths and remove checksums before sweep.
  unparse [-o] [file] Write the current metadata graph to a file
                   -o, --overwrite: Overwrite the original opened file.
  diff [viewer ...] Compare original file vs current in-memory state
                   Default viewer: meld
  undo             Undo the last mutating operation (drop / sweep)
  redo             Re-apply the last undone operation
  history          Show available undo/redo entries
  help             Show this help message
  exit / quit      Exit the REPL
""".strip() + "\n")

def parse_repl_line(line: str) -> tuple[str, dict[str, Any], str]:
    """Parses a REPL line into (command, flags, payload)."""
    parts = line.strip().split(maxsplit=1)
    if not parts:
        return "", {}, ""

    cmd = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    flags = {
        "verbose": False, 
        "depth": -1, 
        "force": False, 
        "summary": False,
        "flat": False,
        "all": False,
        "reduce": False,
        "overwrite": False
    }
    while rest:
        rest = rest.strip()
        sub_parts = rest.split(maxsplit=1)
        word = sub_parts[0]

        if word in ("-v", "--verbose"):
            flags["verbose"] = True
        elif word in ("-a", "--all"):
            flags["all"] = True
        elif word in ("-r", "--reduce"):
            flags["reduce"] = True
        elif word in ("-n", "--node-only"):
            flags["depth"] = 0
            if len(sub_parts) > 1:
                peek_parts = sub_parts[1].split(maxsplit=1)
                # Only consume the digit as depth if it's not the last word.
                # If it's the last word, assume it's the node ID (payload).
                if peek_parts[0].isdigit() and len(peek_parts) > 1:
                    flags["depth"] = int(peek_parts[0])
                    rest = peek_parts[1]
                    continue
        elif word in ("-s", "--summary"):
            flags["summary"] = True
        elif word in ("-l", "--list"):
            flags["flat"] = True
        elif word in ("-f", "--force"):
            flags["force"] = True
        elif word in ("-o", "--overwrite"):
            flags["overwrite"] = True
        else:
            break

        rest = sub_parts[1] if len(sub_parts) > 1 else ""

    return cmd, flags, rest.strip()

def is_matcher_expression(payload: str) -> bool:
    """Heuristic to distinguish between a node ID and a matcher expression."""
    p = payload.strip()
    if not p:
        return False
    # If it starts with ! and has no parens, it's almost certainly an ID
    if p.startswith("!") and "(" not in p:
        return False
    # If it's purely digits, it's an ID
    if p.isdigit():
        return False
    # If it has parens, we treat it as a matcher expression
    return "(" in p and ")" in p


def _normalize_node_id(payload: str) -> str:
    return payload[1:] if payload.startswith("!") else payload


def _format_result(res: MatchResult, flags: dict[str, Any]) -> str:
    if flags["flat"]:
        return format_flat_list(
            res,
            depth=flags["depth"],
            name_only=flags["summary"],
        )
    return format_ascii_tree(
        res,
        verbose=flags["verbose"],
        depth=flags["depth"],
        name_only=flags["summary"],
    )


def _compile_matcher(payload: str, sandbox_globals: dict[str, Any]) -> Any:
    matcher = execute_safely(payload, sandbox_globals)
    if not matcher or not hasattr(matcher, "matches"):
        raise ValueError("Query did not return a valid Matcher object.")
    return matcher


def _evaluate_matches(manager: IRManager, matcher: Any) -> list[MatchResult]:
    return list(evaluate_query(manager.node_map.values(), matcher))


def _handle_match_command(
    manager: IRManager,
    flags: dict[str, Any],
    payload: str,
    sandbox_globals: dict[str, Any],
) -> None:
    if not payload:
        print("Error: Must provide a query.")
        return

    try:
        matcher = _compile_matcher(payload, sandbox_globals)
        results = _evaluate_matches(manager, matcher)

        if not results:
            print("0 matches found.")
            return

        for i, res in enumerate(results, 1):
            print(f"\nMatch {i} at !{res.node.id}:")
            print(_format_result(res, flags))
        print(f"\nTotal matches: {len(results)}")
    except (SecurityError, ValueError, NameError) as e:
        print(f"Query Error: {e}")
    except Exception as e:
        print(f"Execution Error: {e}")


def _handle_print_command(
    manager: IRManager,
    flags: dict[str, Any],
    payload: str,
) -> None:
    if not payload:
        print("Error: Must provide a node ID to print.")
        return

    target = _normalize_node_id(payload)
    node = manager.node_map.get(target)
    if not node:
        print(f"Error: Node !{target} not found.")
        return

    res = MatchResult(node)
    print(f"\nNode !{node.id}:")
    print(_format_result(res, flags))


def _handle_drop_command(
    manager: IRManager,
    flags: dict[str, Any],
    payload: str,
    sandbox_globals: dict[str, Any],
) -> None:
    if not payload:
        print("Error: Must provide a node ID to drop.")
        return

    if is_matcher_expression(payload):
        try:
            matcher = _compile_matcher(payload, sandbox_globals)
            results = _evaluate_matches(manager, matcher)

            if not results:
                print("0 matches found.")
                return

            target_ids = []
            seen_ids = set()
            for res in results:
                if res.node.id not in seen_ids:
                    target_ids.append(res.node.id)
                    seen_ids.add(res.node.id)

            success_count = 0
            for target_id in target_ids:
                try:
                    if target_id not in manager.node_map:
                        continue
                    drop_node(target_id, manager.node_map, force=flags["force"])
                    success_count += 1
                except ValueError as e:
                    print(f"Failed to drop !{target_id}: {e}")

            print(
                f"Success: Dropped {success_count} matching nodes "
                f"(force={flags['force']})."
            )
            if flags["force"]:
                try:
                    Unparser().validate(manager.node_map)
                except DanglingReferenceError as e:
                    print(f"Warning: Graph is now inconsistent: {e}")
        except (SecurityError, ValueError, NameError) as e:
            print(f"Query Error: {e}")
        except Exception as e:
            print(f"Execution Error: {e}")
        return

    target = _normalize_node_id(payload)
    try:
        drop_node(target, manager.node_map, force=flags["force"])
        print(
            f"Success: Dropped !{target} (force={flags['force']}) "
            "and executed cascade."
        )
        if flags["force"]:
            try:
                Unparser().validate(manager.node_map)
            except DanglingReferenceError as e:
                print(f"Warning: Graph is now inconsistent: {e}")
    except ValueError as e:
        print(f"Failed to drop !{target}: {e}")
    except Exception as e:
        print(f"Error dropping node: {e}")


def _handle_sweep_command(manager: IRManager, flags: dict[str, Any]) -> None:
    try:
        if flags["reduce"]:
            m_count = manager.reduce_difile_nodes()
            print(f"Success: Reduced {m_count} DIFile nodes.")

        count = manager.sweep_unreferenced_metadata(discard_named=flags["all"])
        print(f"Success: Swept {count} unreferenced metadata definitions.")
        print(f"Current count: {len(manager.node_map)} nodes.")
    except Exception as e:
        print(f"Sweep Error: {e}")


def _handle_unparse_command(
    manager: IRManager, 
    flags: dict[str, Any], 
    payload: str, 
    opened_file: str
) -> None:
    target = payload
    if flags["overwrite"]:
        if payload:
            print("Error: Cannot provide a filename when using --overwrite.")
            return
        target = opened_file

    if not target:
        print("Error: Must provide a filename or use --overwrite.")
        return

    try:
        manager.save_file(target)
        print(f"Success: Graph safely written to {target}")
    except DanglingReferenceError as e:
        print(f"Unparse Error: {e}")
        print(
            "Referenced nodes must have definitions. "
            "Use 'undo' or restore the missing nodes."
        )
    except Exception as e:
        print(f"Failed to write file: {e}")


def _handle_diff_command(
    manager: IRManager,
    payload: str,
    opened_file: str,
) -> None:
    viewer_cmd = shlex.split(payload) if payload else ["meld"]
    if not viewer_cmd:
        viewer_cmd = ["meld"]

    opened_basename = os.path.basename(opened_file)
    opened_stem, _ = os.path.splitext(opened_basename)
    tmp_file: Optional[str] = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            delete=False,
            prefix=f"dimeta-query-tmp-{opened_stem}-",
            suffix=".ll",
            dir=tempfile.gettempdir(),
        ) as tmp:
            tmp_file = tmp.name

        manager.save_file(tmp_file)
        subprocess.run(viewer_cmd + [opened_file, tmp_file], check=False)
    except DanglingReferenceError as e:
        print(f"Diff Error: {e}")
    except FileNotFoundError:
        print(f"Diff Error: Viewer '{viewer_cmd[0]}' not found.")
    except Exception as e:
        print(f"Diff Error: {e}")
    finally:
        if tmp_file and os.path.exists(tmp_file):
            try:
                os.remove(tmp_file)
            except OSError:
                pass

_SignatureItem = tuple[str, str, int, bool]
_Signature = tuple[int, tuple[_SignatureItem, ...]]


def _snapshot_signature(manager: IRManager) -> _Signature:
    """Cheap fingerprint of the manager's mutable state.

    Used to decide whether a "mutating" command actually changed anything.
    Avoids recording no-op snapshots (e.g. a ``drop`` against a node ID
    that does not exist, or a ``sweep`` with nothing to remove).
    """
    items = tuple(
        (
            node_id,
            node.raw_text,
            node.ref_count,
            node.is_distinct,
        )
        for node_id, node in sorted(manager.node_map.items())
    )
    return (len(manager.node_map), items)


def _run_with_history(
    history: HistoryManager,
    manager: IRManager,
    label: str,
    func: Any,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Capture, run, then conditionally record a snapshot.

    The pre-mutation snapshot is recorded only if the operation actually
    altered the graph state. This keeps the history stack semantically
    meaningful and avoids wasting space on no-ops.
    """
    pre_signature = _snapshot_signature(manager)
    snapshot = GraphSnapshot.capture(manager)
    func(*args, **kwargs)
    post_signature = _snapshot_signature(manager)
    if pre_signature != post_signature:
        history.record(label, snapshot)


def _handle_undo_command(manager: IRManager, history: HistoryManager) -> None:
    if not history.can_undo():
        print("Nothing to undo.")
        return
    current = GraphSnapshot.capture(manager)
    result = history.undo(current)
    # ``result`` cannot be None here because can_undo() returned True, but
    # we still guard for type-narrowing clarity.
    if result is None:
        print("Nothing to undo.")
        return
    label, snapshot = result
    snapshot.restore(manager)
    print(f"Undone: {label}")


def _handle_redo_command(manager: IRManager, history: HistoryManager) -> None:
    if not history.can_redo():
        print("Nothing to redo.")
        return
    current = GraphSnapshot.capture(manager)
    result = history.redo(current)
    if result is None:
        print("Nothing to redo.")
        return
    label, snapshot = result
    snapshot.restore(manager)
    print(f"Redone: {label}")


def _handle_history_command(history: HistoryManager) -> None:
    undo_labels = history.undo_labels()
    redo_labels = history.redo_labels()
    if not undo_labels and not redo_labels:
        print("History is empty.")
        return

    if undo_labels:
        print("Undo stack (most recent last):")
        for idx, label in enumerate(undo_labels, 1):
            print(f"  {idx}. {label}")
    else:
        print("Undo stack: (empty)")

    if redo_labels:
        print("Redo stack (most recent last):")
        for idx, label in enumerate(redo_labels, 1):
            print(f"  {idx}. {label}")
    else:
        print("Redo stack: (empty)")


def _load_and_init(
    args: argparse.Namespace,
) -> tuple[IRManager, HistoryManager, Dict[str, Any]]:
    """Parse the input file and construct shared state for REPL or TUI."""
    if not os.path.isfile(args.file):
        print(f"Error: File '{args.file}' not found.")
        sys.exit(1)

    print(f"Parsing '{args.file}'...")
    manager = IRManager()

    try:
        manager.parse_file(args.file)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

    print(
        f"Loaded {len(manager.node_map)} nodes from "
        f"{manager.metadata_count} metadata definitions."
    )

    if manager.unresolved:
        print(
            f"Warning: {len(manager.unresolved)} proxy nodes were "
            f"referenced but never defined."
        )

    sandbox_globals = setup_sandbox_globals()
    history = HistoryManager()
    return manager, history, sandbox_globals


def dispatch_command(
    cmd: str,
    flags: Dict[str, Any],
    payload: str,
    manager: IRManager,
    history: HistoryManager,
    sandbox_globals: Dict[str, Any],
    opened_file: str,
) -> bool:
    """Execute one parsed REPL command.

    Returns True if the command was recognized and dispatched; False if it
    was unknown. Mirrors the if/elif ladder used in the interactive REPL so
    that both the REPL and the TUI share a single dispatch path.
    """
    if cmd == "m":
        _handle_match_command(manager, flags, payload, sandbox_globals)
    elif cmd == "p":
        _handle_print_command(manager, flags, payload)
    elif cmd == "drop":
        _run_with_history(
            history,
            manager,
            f"drop {payload}" if payload else "drop",
            _handle_drop_command,
            manager,
            flags,
            payload,
            sandbox_globals,
        )
    elif cmd == "sweep":
        sweep_label_parts = ["sweep"]
        if flags["reduce"]:
            sweep_label_parts.append("-r")
        if flags["all"]:
            sweep_label_parts.append("-a")
        _run_with_history(
            history,
            manager,
            " ".join(sweep_label_parts),
            _handle_sweep_command,
            manager,
            flags,
        )
    elif cmd == "unparse":
        _handle_unparse_command(manager, flags, payload, opened_file)
    elif cmd == "diff":
        _handle_diff_command(manager, payload, opened_file)
    elif cmd == "undo":
        _handle_undo_command(manager, history)
    elif cmd == "redo":
        _handle_redo_command(manager, history)
    elif cmd == "history":
        _handle_history_command(history)
    else:
        return False
    return True


def run_repl(
    manager: IRManager,
    history: HistoryManager,
    sandbox_globals: Dict[str, Any],
    opened_file: str,
) -> None:
    """Run the classic line-based REPL."""
    print("Type 'help' for available commands.")

    while True:
        try:
            user_input = input("dimeta> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not user_input:
            continue

        cmd, flags, payload = parse_repl_line(user_input)

        if cmd in ("exit", "quit"):
            break

        if cmd == "help":
            print_help()
            continue

        if not dispatch_command(
            cmd, flags, payload, manager, history, sandbox_globals, opened_file
        ):
            print("Unknown command. Type 'help' for options.")


def _should_use_tui(args: argparse.Namespace) -> bool:
    """Decide whether to launch the TUI for this invocation."""
    if args.no_tui:
        return False
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    return importlib.util.find_spec("textual") is not None


def main() -> None:

    parser = argparse.ArgumentParser(
        description="dimeta-query: Interactive LLVM Metadata Query Engine"
    )
    parser.add_argument("file", help="Path to the .ll file to analyze")
    parser.add_argument(
        "--no-tui",
        "--repl",
        dest="no_tui",
        action="store_true",
        help="Force the classic line-based REPL instead of the Textual TUI.",
    )
    args = parser.parse_args()

    manager, history, sandbox_globals = _load_and_init(args)

    if _should_use_tui(args):
        try:
            from .tui import run_tui
        except ImportError as e:
            print(
                f"TUI dependencies unavailable ({e}); falling back to REPL. "
                "Install with: pip install dimeta-query[tui]"
            )
            run_repl(manager, history, sandbox_globals, args.file)
            return
        run_tui(manager, history, sandbox_globals, args.file)
        return

    # REPL fallback path
    if not args.no_tui and sys.stdout.isatty():
        # User likely wanted the TUI but Textual isn't installed.
        print(
            "Textual not installed; falling back to REPL. "
            "Install with: pip install dimeta-query[tui]"
        )
    run_repl(manager, history, sandbox_globals, args.file)


if __name__ == "__main__":
    main()
