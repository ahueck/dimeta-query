# dimeta-query

*dimeta-query* is a Python-based tool for parsing and querying LLVM metadata based on `*.ll` (text) files.
It provides a CLI and a programmatic interface for exploring and manipulating the metadata graph.

*Disclaimer*: This tool has been created with support of an agentic AI tool.

## Usage

Run the CLI on an LLVM IR file to open the interactive query engine:

```bash
$ dimeta-query --help
usage: dimeta-query [-h] file

dimeta-query: Interactive LLVM Metadata Query Engine

positional arguments:
  file        Path to the .ll file to analyze

options:
  -h, --help  show this help message and exit
```

### Interactive Session Examples

#### 1. Finding a specific type by name
Use the `m` (match) command with the `composite_type` and `has_name` matchers.

```bash
dimeta> m composite_type(has_name("chunk_type"))

Match 1 at !18:
!18 = distinct !DICompositeType(tag: DW_TAG_structure_type, name: "chunk_type", scope: !6, file: !1, line: 29, size: 4256, elements: !19)
└─ elements: !19 = !{!20, !21, !22, !23, !24, !25, !26, !27, !28, !29, !30, !31, !35, !40, !41, !42, !43, !44, !45, !46, !47, !73, !74, !75}
    ├─ [0]: !20 = !DIDerivedType(tag: DW_TAG_member, name: "task", baseType: !11, size: 32, align: 32)
    │   ├─ scope: !18 = <cycle to !18 = DICompositeType>
    │   └─ baseType: !11 = !DIBasicType(name: "integer", size: 32, encoding: DW_ATE_signed)
    ├─ [1]: !21 = !DIDerivedType(tag: DW_TAG_member, name: "chunk_x_min", baseType: !11, size: 32, align: 32, offset: 32)
...
Total matches: 1
```

#### 2. Using Fuzzy Matching
Find all local variables whose name starts with "chunk_".

```bash
dimeta> m -n local_variable(has_name(fuzzy("^chunk_.*")))

Match 1 at !150:
!150 = !DILocalVariable(name: "chunk_x", scope: !145, file: !1, line: 102, type: !11)

Match 2 at !152:
!152 = !DILocalVariable(name: "chunk_y", scope: !145, file: !1, line: 102, type: !11)

Total matches: 2
```

#### 3. Nested Matchers
Find composite types that have a member named "task".

```bash
dimeta> m composite_type(has_element(derived_type(has_name("task"))))

Match 1 at !18:
!18 = distinct !DICompositeType(tag: DW_TAG_structure_type, name: "chunk_type", ...)
...
```

#### 4. Printing and Navigation
Use the `p` (print) command to inspect a node by ID. Use `-n` to limit depth.

```bash
dimeta> p -n 1 !18
Node !18:
!18 = distinct !DICompositeType(tag: DW_TAG_structure_type, name: "chunk_type", scope: !6, file: !1, line: 29, size: 4256, elements: !19)
└─ elements: !19 = !{!20, !21, ...}
```

#### 5. Clean Metadata
Remove metadata nodes that are no longer reachable from any IR statement or named metadata.

```bash
dimeta> sweep
Success: Swept 12 unreferenced metadata definitions.
Current count: 45 nodes.
```

### Available Commands

| Command             | Description                                                                        |
|:--------------------|:-----------------------------------------------------------------------------------|
| `m <flags> <query>` | Evaluate a matcher query. Returns all nodes in the graph that match the criteria.  |
| `p <flags> <id>`    | Print a specific node by its metadata ID (e.g., `p !42` or `p 42`).                |
| `drop <id>`         | Safely remove a node. Use `-f` to force removal of referenced nodes.               |
| `sweep [-a]`        | Remove metadata nodes not reachable from IR. Use `-a` to also discard named nodes. |
| `unparse <file>`    | Export the current (potentially modified) metadata graph to a `.ll` file.          |
| `help`              | Show detailed command help.                                                        |
| `exit`              | Exit the REPL.                                                                     |

#### Output Formatting Flags (for `m` and `p`)

Both the match (`m`) and print (`p`) commands support flags to control how the resulting metadata tree is displayed:

*   **`-v`, `--verbose`**: Includes property names in the tree visualization (e.g., `scope: !10` instead of just `!10`).
*   **`-n`, `--node-only [depth]`**: Limits the depth of the tree traversal.
    *   `m -n composite_type(...)`: Shows only the matching nodes (depth 0).
    *   `m -n 1 ...`: Shows matching nodes and their immediate children.
*   **`-s`, `--summary`**: Concise output showing only the node ID and its DWARF tag or type, omitting the full attribute payload.
*   **`-l`, `--list`**: Displays the results as a flat, deduplicated list of nodes instead of a hierarchical tree.

**Example: Summary List of matches**
```bash
dimeta> m -s -l local_variable()
!150 = DILocalVariable
!152 = DILocalVariable
!160 = DILocalVariable
```

### Query Matchers and Modifiers

*   **Node Types**: `node()`, `local_variable()`, `composite_type()`, `derived_type()`, `basic_type()`, `subprogram()`, `file_node()`, etc.
*   **Property Matchers**: `has_name("foo")`, `has_tag("DW_TAG_...")`, `has_flag("DIFlagArtificial")`, `has_attr("name", "value")`.
*   **Traversal Matchers**: `has_type()`, `has_scope()`, `has_element()`, `has_base_type()`, `has_child()`.
*   **String Modifiers**: `fuzzy("regex")`, `demangle("expected_name")`.


## Installation

### Via pip

Install directly from the source:

```bash
pip install .
```

For development, install with the `dev` and `test` extras:

```bash
pip install -e ".[dev,test]"
```

### Standalone Executable

Build a self-contained `.pyz` executable using `shiv` in folder `dist/`.

```bash
$ make build
 > rm -rf build dist
 > mkdir -p dist
 > shiv --compressed -o dist/dimeta-query.pyz -e dimeta_query.cli:main .
```

## Development

The project tools are governed by the `Makefile` and `pyproject.toml`.

### Running Tests

We use `pytest` for testing.

```bash
$ pytest --tb=short
============================= test session starts ==============================
...
tests/test_cli.py .............                                          [ 13%]
...
tests/test_unparser.py .                                                 [100%]

======================== 94 passed, 1 skipped in 8.20s =========================
```

### Linting and Type Checking 

Code style and linting are enforced by `ruff`.
Static type checking is provided by `mypy`.

```bash
$ ruff check .
$ mypy src
```

## Project Structure

```text
src/dimeta_query/
├── __init__.py
├── __main__.py
├── cli.py            # CLI entry point and argument parsing
├── formatter.py      # Output formatting and tree visualization
├── grammar.lark      # Lark grammar rules for LLVM metadata syntax
├── graph_manager.py  # Graph mutation, reference tracking, and garbage collection
├── ir.py             # Raw LLVM IR text processing and reference extraction
├── matchers.py       # Specific query matchers for node types and properties
├── model.py          # Core data models (MDNode, MDSpecializedNode, etc.)
├── modifiers.py      # String modifiers for queries (e.g., fuzzy, demangle)
├── parser.py         # Lark-based parser for building the metadata graph
├── query.py          # Query execution engine and base matching logic
├── repl.py           # Interactive query and manipulation shell
└── unparser.py       # Graph state validation and structural checks
tests/                # Test suite
```