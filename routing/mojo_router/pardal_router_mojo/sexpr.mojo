from python import Python, PythonObject

comptime py = Python


fn scan_first_quoted_string(src: String) raises -> String:
    """Return the first quoted-string token from `src` (decoded).

    Used for regression tests on DSN fixtures that contain Windows paths like
    `"C:\\Work\\..."` where backslashes must be preserved.
    """
    var i = 0
    var at_line_start = True
    while i < len(src):
        var ch = String(src[byte=i])
        if ch == String("\n"):
            at_line_start = True
        # Treat ';' as a comment marker only at the start of a line (FreeRouting
        # fixtures use literal ';' atoms inside lists, e.g. (PN ;)).
        if ch == String(";") and at_line_start:
            i += 1
            while i < len(src):
                ch = String(src[byte=i])
                i += 1
                if ch == String("\n"):
                    at_line_start = True
                    break
            continue
        if ch != String("\""):
            i += 1
            if ch != String(" ") and ch != String("\t") and ch != String("\r"):
                at_line_start = False
            continue

        # Skip DSN's `"` standalone token, as in `(string_quote ")`.
        if i + 1 < len(src):
            var nxt0 = String(src[byte=i + 1])
            if nxt0 == String(")") or nxt0 == String(" ") or nxt0 == String("\t") or nxt0 == String("\n") or nxt0 == String("\r"):
                i += 1
                continue

            i += 1
            var s = String("")
            while i < len(src):
                ch = String(src[byte=i])
                if ch == String("\""):
                    return s
                if ch == String("\\"):
                    if i + 1 >= len(src):
                        raise Error("sexpr: unterminated escape sequence")
                    var nxt = String(src[byte=i + 1])
                    if nxt == String("\\") or nxt == String("\""):
                        s += nxt
                        i += 2
                        continue
                    # DSN Windows paths: preserve backslashes literally (keep '\\').
                    s += String("\\")
                    s += nxt
                    i += 2
                    continue
                s += ch
                i += 1
            raise Error("sexpr: unterminated string")

    raise Error("sexpr: no quoted string found")


fn parse_sexpr(src: String) raises -> PythonObject:
    """Parse a minimal subset of S-expressions used by DSN/RULES/SES fixtures.

    This parser is intentionally small and aimed at regression tests against
    FreeRouting fixtures. It:
    - parses parentheses-delimited lists and atoms
    - supports quoted strings with basic backslash escapes (\\, \", \\n, \\t, \\r)
    - skips ';' line comments (outside strings)

    Return value is a Python `list` of expressions, where each expression is:
    - a Python `str` (atom), or
    - a Python `list` (nested expression list)
    """
    var out = py.list()
    var stack = List[PythonObject]()

    var i = 0
    var at_line_start = True
    while i < len(src):
        var ch = String(src[byte=i])

        if ch == String(" ") or ch == String("\t") or ch == String("\n") or ch == String("\r"):
            if ch == String("\n"):
                at_line_start = True
            i += 1
            continue

        # Line comment until newline.
        if ch == String(";") and at_line_start:
            i += 1
            while i < len(src):
                ch = String(src[byte=i])
                i += 1
                if ch == String("\n"):
                    at_line_start = True
                    break
            continue

        if ch == String("("):
            stack.append(py.list())
            at_line_start = False
            i += 1
            continue

        if ch == String(")"):
            if len(stack) == 0:
                raise Error("sexpr: unexpected ')'")
            var items = stack.pop()
            if len(stack) > 0:
                stack[len(stack) - 1].append(items)
            else:
                out.append(items)
            at_line_start = False
            i += 1
            continue

        # Quoted string token.
        if ch == String("\""):
            # DSN/RULES sometimes uses a standalone '"' atom, e.g. `(string_quote ")`.
            # Treat it as an atom when it's immediately followed by whitespace or ')'.
            if i + 1 < len(src):
                var nxt0 = String(src[byte=i + 1])
                if nxt0 == String(")") or nxt0 == String(" ") or nxt0 == String("\t") or nxt0 == String("\n") or nxt0 == String("\r"):
                    if len(stack) > 0:
                        stack[len(stack) - 1].append(PythonObject(String("\"")))
                    else:
                        out.append(PythonObject(String("\"")))
                    at_line_start = False
                    i += 1
                    continue
            i += 1
            var s = String("")
            var closed = False
            while i < len(src):
                ch = String(src[byte=i])
                if ch == String("\""):
                    closed = True
                    i += 1
                    break
                if ch == String("\\"):
                    if i + 1 >= len(src):
                        raise Error("sexpr: unterminated escape sequence")
                    var nxt = String(src[byte=i + 1])
                    if nxt == String("\\") or nxt == String("\""):
                        s += nxt
                        i += 2
                        continue
                    # Unknown escapes (e.g. Windows path backslashes): preserve literally.
                    s += String("\\")
                    s += nxt
                    i += 2
                    continue
                s += ch
                i += 1
            if not closed:
                raise Error("sexpr: unterminated string")
            if len(stack) > 0:
                stack[len(stack) - 1].append(PythonObject(s))
            else:
                out.append(PythonObject(s))
            at_line_start = False
            continue

        # Atom token (stops at whitespace, parens, quotes, or comment start).
        var s = String("")
        while i < len(src):
            ch = String(src[byte=i])
            if ch == String(" ") or ch == String("\t") or ch == String("\n") or ch == String("\r") or ch == String("(") or ch == String(")") or ch == String("\""):
                break
            s += ch
            i += 1
        if len(s) == 0:
            raise Error("sexpr: internal error (empty atom)")
        if len(stack) > 0:
            stack[len(stack) - 1].append(PythonObject(s))
        else:
            out.append(PythonObject(s))
        at_line_start = False

    if len(stack) != 0:
        raise Error("sexpr: unterminated '('")

    return out
