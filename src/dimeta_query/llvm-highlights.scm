; This file was originally copied from tree-sitter-llvm 1.1.0 (MIT license)
; (queries/highlights.scm) and extended by dimeta-query with additional
; captures for LLVM debug-info metadata. Search for "Metadata extensions"
; below to find the dimeta-query additions.

(type) @type
(type_keyword) @type.builtin

(type [
    (local_var)
    (global_var)
  ] @type)

(argument) @variable.parameter

(_ inst_name: _ @keyword.operator)

[
  "catch"
  "filter"
] @keyword.operator

[
  "to"
  "nneg"
  "nuw"
  "nsw"
  "exact"
  "disjoint"
  "unwind"
  "from"
  "cleanup"
  "swifterror"
  "volatile"
  "inbounds"
  "inrange"
] @keyword.control
(icmp_cond) @keyword.control
(fcmp_cond) @keyword.control

(fast_math) @keyword.control

(_ callee: _ @function)
(function_header name: _ @function)

[
  "declare"
  "define"
] @keyword.function
(calling_conv) @keyword.function

[
  "target"
  "triple"
  "datalayout"
  "source_filename"
  "addrspace"
  "blockaddress"
  "align"
  "syncscope"
  "within"
  "uselistorder"
  "uselistorder_bb"
  "module"
  "asm"
  "sideeffect"
  "alignstack"
  "inteldialect"
  "unwind"
  "type"
  "global"
  "constant"
  "externally_initialized"
  "alias"
  "ifunc"
  "section"
  "comdat"
  "thread_local"
  "localdynamic"
  "initialexec"
  "localexec"
  "any"
  "exactmatch"
  "largest"
  "nodeduplicate"
  "samesize"
  "distinct"
  "attributes"
  "vscale"
  "no_cfi"
] @keyword

(linkage_aux) @keyword
(dso_local) @keyword
(visibility) @keyword
(dll_storage_class) @keyword
(unnamed_addr) @keyword
(attribute_name) @keyword

(function_header [
    (linkage)
    (calling_conv)
    (unnamed_addr)
  ] @keyword.function)

(number) @constant.numeric.integer
(comment) @comment
(string) @string
(cstring) @string
(label) @label
(_ inst_name: "ret" @keyword.control.return)
(float) @constant.numeric.float

[
  (local_var)
  (global_var)
] @variable

[
  (struct_value)
  (array_value)
  (vector_value)
] @constructor

[
  "("
  ")"
  "["
  "]"
  "{"
  "}"
  "<"
  ">"
  "<{"
  "}>"
] @punctuation.bracket

[
  ","
  ":"
] @punctuation.delimiter

[
  "="
  "|"
  "x"
  "..."
] @operator

[
  "true"
  "false"
] @constant.builtin.boolean

[
  "undef"
  "poison"
  "null"
  "none"
  "zeroinitializer"
] @constant.builtin

(ERROR) @error

; --- Metadata extensions (dimeta-query) ----------------------------------
;
; These captures highlight LLVM debug-info metadata that the upstream
; tree-sitter-llvm highlights.scm leaves uncoloured. All scope names below
; are chosen from those defined in Textual's built-in monokai theme so
; they actually render.

; The left-hand side of `!N = ...` is a definition marker.
(global_metadata (metadata_ref) @tag)

; Attachment names like `!dbg`, `!tbaa`, `!prof`.
(metadata_attachment (metadata_name) @tag)
(metadata_refs (metadata_name) @tag)

; The specialized-metadata kind: `!DICompileUnit`, `!DIFile`, `!DILocation`.
; Only metadata_ref tokens whose text starts with a letter (after `!`) are
; kind names; the same shape covers bare references like `!4`, so we use a
; regex predicate to discriminate.
((specialized_md (metadata_ref) @type.builtin)
  (#match? @type.builtin "^![A-Za-z]"))

; Numeric metadata references like `!1`, `!42`. These appear wrapped in
; `metadata > specialized_md > metadata_ref` in attachments, tuple
; elements, and argument values.
((specialized_md (metadata_ref) @number)
  (#match? @number "^![0-9]"))

; Argument keys inside `!DIFoo(key: value, ...)` — camelCase identifiers
; that are bare specialized_md_value tokens. Excludes the small set of
; reserved value keywords (`true`/`false`/`null`/`undef`/`poison`/`none`/
; `zeroinitializer`) which the upstream scm already colours.
((specialized_md_value) @yaml.field
  (#match? @yaml.field "^[a-z][a-zA-Z0-9_]*$")
  (#not-match? @yaml.field
   "^(true|false|null|undef|poison|none|zeroinitializer)$"))

; DWARF enumeration constants like `DW_LANG_C99`, `DW_TAG_subprogram`,
; `DW_ATE_signed`, `DW_OP_constu`, `DW_FORM_data4`, etc.
((specialized_md_value) @constant.builtin
  (#match? @constant.builtin "^DW_[A-Z]+_[A-Za-z0-9_]+$"))

; DIFlag bitmask constants: `DIFlagPrototyped`, `DIFlagPublic`, ...
((specialized_md_value) @constant.builtin
  (#match? @constant.builtin "^DIFlag[A-Z][A-Za-z0-9_]*$"))

; emissionKind / nameTableKind / runtimeLang style enum values.
((specialized_md_value) @constant.builtin
  (#match? @constant.builtin
   "^(FullDebug|LineTablesOnly|NoDebug|DebugDirectivesOnly|Default|GNU|Apple)$"))
