import ast
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from reliability.risk_assessor import assess_risk

# Directory where prompt templates live, relative to this file
PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")


def _load_prompt(filename: str) -> str:
    """Load a prompt template from the prompts/ folder."""
    path = os.path.join(PROMPTS_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ----------------------------
# Heuristic rules (offline mode)
# ----------------------------
FIX_COMMENT = "# [Game Glitch Investigator] log or handle the error"
_EXCEPT_PASS_MSG = "Suppressed exception"


def _ensure_import(code: str, module: str) -> str:
    """Add `import <module>` if missing, after any module docstring / __future__ imports."""
    if re.search(rf"^[ \t]*import\s+[^\n]*\b{module}\b", code, flags=re.MULTILINE):
        return code

    pos = 0
    try:
        for i, node in enumerate(ast.parse(code).body):
            is_doc = (
                i == 0
                and isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            )
            is_future = isinstance(node, ast.ImportFrom) and node.module == "__future__"
            if not (is_doc or is_future):
                break
            pos = node.end_lineno
    except SyntaxError:
        pass

    lines = code.split("\n")
    new_lines = lines[:pos] + ([""] if pos else []) + [f"import {module}"] + ([] if pos else [""]) + lines[pos:]
    return "\n".join(new_lines)


def _find_matching_paren(code: str, open_idx: int) -> int:
    """Index of the ')' matching the '(' at open_idx (skipping simple string literals), or -1."""
    depth = 0
    quote = None
    i = open_idx
    while i < len(code):
        ch = code[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


_REQUESTS_CALL = re.compile(r"(?<![\w.])requests\.(?:get|post|put|patch|delete|head|options|request)\s*\(")
_IS_LITERAL_LINE = re.compile(r"^\s*(if|elif|while|assert|return)\b")
_IS_LITERAL = re.compile(r"\bis\s+(?:not\s+)?(?=\d|[\"'])")
_SECRET = re.compile(
    r"^([ \t]*)([A-Za-z_]*(?:password|passwd|secret|api_?key|token)[A-Za-z_]*)[ \t]*=[ \t]*([\"'])(?!\3)[^\"'\n]+\3",
    flags=re.MULTILINE | re.IGNORECASE,
)
_MUTABLE_DEFAULT = re.compile(
    r"(\b\w+(?:[ \t]*:[ \t]*[^=,()]+?)?[ \t]*=[ \t]*)(\[\]|\{\}|set\(\)|list\(\)|dict\(\))(?=\s*(?:[,)]|$))"
)
_DEF_LINE = re.compile(r"^([ \t]*)(?:async[ \t]+)?def[ \t]+\w+[ \t]*\((.*)\)[ \t]*(?:->[^:\n]+)?:[ \t]*$")
_PRINT_KWARGS = re.compile(r"\b(file|end|sep|flush)\s*=")


def _requests_calls_missing_timeout(code: str) -> List[int]:
    """Indices of the closing ')' of each requests.* call that has no timeout argument."""
    closes = []
    for m in _REQUESTS_CALL.finditer(code):
        close = _find_matching_paren(code, m.end() - 1)
        if close != -1 and "timeout" not in code[m.end():close]:
            closes.append(close)
    return closes


# --- detectors -------------------------------------------------------------
def _detect_print(code: str) -> bool:
    return bool(re.search(r"(?<![\w.])print\s*\(", code))


def _detect_bare_except(code: str) -> bool:
    return bool(re.search(r"^[ \t]*except[ \t]*:", code, flags=re.MULTILINE))


def _detect_swallowed_exception(code: str) -> bool:
    multi = r"^[ \t]*except\b[^\n]*:[ \t]*\n(?:[ \t]*#[^\n]*\n)*[ \t]*pass\b"
    single = r"^[ \t]*except\b[^\n]*:[ \t]*pass\b"
    return bool(re.search(multi, code, flags=re.MULTILINE) or re.search(single, code, flags=re.MULTILINE))


def _detect_todo(code: str) -> bool:
    return bool(re.search(r"\b(TODO|FIXME|XXX|HACK)\b", code))


def _detect_mutable_default(code: str) -> bool:
    return bool(re.search(r"\bdef\s+\w+\s*\([^)]*=\s*(\[\]|\{\}|set\(\)|list\(\)|dict\(\))", code))


def _detect_none_comparison(code: str) -> bool:
    return bool(re.search(r"[=!]=\s*None\b", code))


def _detect_is_literal(code: str) -> bool:
    return any(_IS_LITERAL.search(line) for line in code.split("\n") if _IS_LITERAL_LINE.match(line))


def _detect_bool_comparison(code: str) -> bool:
    return bool(re.search(r"[=!]=\s*(True|False)\b", code))


def _detect_eval_exec(code: str) -> bool:
    return bool(re.search(r"(?<![\w.])(eval|exec)\s*\(", code))


def _detect_hardcoded_secret(code: str) -> bool:
    return bool(_SECRET.search(code))


def _detect_requests_no_timeout(code: str) -> bool:
    return bool(_requests_calls_missing_timeout(code))


def _detect_open_without_with(code: str) -> bool:
    return bool(re.search(r"^[ \t]*\w+[ \t]*=[ \t]*open\(", code, flags=re.MULTILINE))


def _detect_debugger(code: str) -> bool:
    return bool(
        re.search(r"^[ \t]*(import\s+i?pdb\b|(i?pdb\.set_trace|breakpoint)\s*\(\s*\))", code, flags=re.MULTILINE)
    )


def _detect_infinite_loop(code: str) -> bool:
    has_loop = re.search(r"\bwhile\s+(True|1)\s*:", code)
    has_exit = re.search(r"\b(break|return|raise|sys\.exit|exit)\b", code)
    return bool(has_loop and not has_exit)


def _detect_wildcard_import(code: str) -> bool:
    return bool(re.search(r"^\s*from\s+\S+\s+import\s+\*", code, flags=re.MULTILINE))


def _detect_off_by_one_range(code: str) -> bool:
    return bool(re.search(r"\brange\s*\(\s*len\([^)]*\)\s*\+\s*1\s*\)", code))


# --- fixers ----------------------------------------------------------------
def _fix_print(code: str) -> str:
    out, changed = [], False
    for line in code.split("\n"):
        # logging.info() does not accept print()'s keyword arguments, so leave those alone
        new = line if _PRINT_KWARGS.search(line) else re.sub(r"(?<![\w.])print\s*\(", "logging.info(", line)
        changed = changed or new != line
        out.append(new)
    fixed = "\n".join(out)
    return _ensure_import(fixed, "logging") if changed else fixed


def _fix_swallowed_exception(code: str) -> str:
    multi = re.compile(r"^([ \t]*)(except\b[^\n]*:[ \t]*\n(?:[ \t]*#[^\n]*\n)*)([ \t]*)pass\b", flags=re.MULTILINE)
    single = re.compile(r"^([ \t]*)(except\b[^\n]*:)[ \t]*pass\b[ \t]*$", flags=re.MULTILINE)

    fixed = multi.sub(
        lambda m: f'{m.group(1)}{m.group(2)}{m.group(3)}logging.exception("{_EXCEPT_PASS_MSG}")', code
    )
    fixed = single.sub(
        lambda m: f'{m.group(1)}{m.group(2)}\n{m.group(1)}    logging.exception("{_EXCEPT_PASS_MSG}")', fixed
    )
    return _ensure_import(fixed, "logging") if fixed != code else fixed


def _fix_bare_except(code: str) -> str:
    def repl(m: "re.Match[str]") -> str:
        indent, rest = m.group(1), m.group(2).strip()
        header = f"{indent}except Exception as e:"
        if not rest or rest.startswith("#"):
            return f"{header}{('  ' + rest) if rest else ''}\n{indent}    {FIX_COMMENT}"
        return f"{header}\n{indent}    {FIX_COMMENT}\n{indent}    {rest}"

    return re.sub(r"^([ \t]*)except[ \t]*:[ \t]*([^\n]*)$", repl, code, flags=re.MULTILINE)


def _fix_mutable_defaults(code: str) -> str:
    lines = code.split("\n")
    out: List[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _DEF_LINE.match(line)
        found = list(_MUTABLE_DEFAULT.finditer(m.group(2))) if m else []
        if not found:
            out.append(line)
            i += 1
            continue

        names = [re.match(r"\w+", f.group(1)).group(0) for f in found]
        defaults = [f.group(2) for f in found]
        out.append(_MUTABLE_DEFAULT.sub(r"\1None", line))
        i += 1

        # Put the guard after the docstring, if there is one
        body_indent = m.group(1) + "    "
        if i < len(lines):
            nxt = lines[i].strip()
            body_indent = re.match(r"[ \t]*", lines[i]).group(0) or body_indent
            quote = next((q for q in ('"""', "'''") if re.match(rf"[rRuU]?{q}", nxt)), None)
            if quote:
                out.append(lines[i])
                closed = nxt.count(quote) >= 2
                i += 1
                while not closed and i < len(lines):
                    out.append(lines[i])
                    closed = quote in lines[i]
                    i += 1

        for name, default in zip(names, defaults):
            out.append(f"{body_indent}if {name} is None:")
            out.append(f"{body_indent}    {name} = {default}")
    return "\n".join(out)


def _fix_none_comparison(code: str) -> str:
    fixed = re.sub(r"\s*!=\s*None\b", " is not None", code)
    return re.sub(r"\s*==\s*None\b", " is None", fixed)


def _fix_is_literal(code: str) -> str:
    out = []
    for line in code.split("\n"):
        if _IS_LITERAL_LINE.match(line):
            line = re.sub(r"\bis\s+not\s+(?=\d|[\"'])", "!= ", line)
            line = re.sub(r"\bis\s+(?=\d|[\"'])", "== ", line)
        out.append(line)
    return "\n".join(out)


def _fix_hardcoded_secret(code: str) -> str:
    fixed = _SECRET.sub(lambda m: f'{m.group(1)}{m.group(2)} = os.environ.get("{m.group(2).upper()}")', code)
    return _ensure_import(fixed, "os") if fixed != code else fixed


def _fix_requests_timeout(code: str) -> str:
    for close in sorted(_requests_calls_missing_timeout(code), reverse=True):
        head = code[:close].rstrip()
        gap = code[len(head):close]
        insert = " timeout=10" if head.endswith(",") else ", timeout=10"
        code = head + insert + gap + code[close:]
    return code


def _fix_debugger(code: str) -> str:
    code = re.sub(r"^[ \t]*import\s+i?pdb[ \t]*\n?", "", code, flags=re.MULTILINE)
    return re.sub(
        r"^([ \t]*)(?:i?pdb\.set_trace|breakpoint)\s*\(\s*\)[ \t]*$",
        r"\1pass  # [Game Glitch Investigator] removed debugger call",
        code,
        flags=re.MULTILINE,
    )


# Order matters for fixes: the swallowed-exception fix runs before the bare-except fix so a
# one-line `except: pass` is expanded first and then given a specific exception type.
HEURISTIC_RULES: List[Dict[str, Any]] = [
    {"id": "print", "type": "Code Quality", "severity": "Low",
     "msg": "Found print statements. Consider using logging for non-toy code.",
     "detect": _detect_print, "fix": _fix_print},
    {"id": "wildcard_import", "type": "Code Quality", "severity": "Low",
     "msg": "Found `from x import *`. Wildcard imports hide where names come from and can shadow others.",
     "detect": _detect_wildcard_import, "fix": None},
    {"id": "none_comparison", "type": "Code Quality", "severity": "Low",
     "msg": "Found `== None` / `!= None`. Use `is None` / `is not None`.",
     "detect": _detect_none_comparison, "fix": _fix_none_comparison},
    {"id": "bool_comparison", "type": "Code Quality", "severity": "Low",
     "msg": "Found comparison to True/False. Use the value directly (`if x:` / `if not x:`).",
     "detect": _detect_bool_comparison, "fix": None},
    {"id": "debugger", "type": "Code Quality", "severity": "Medium",
     "msg": "Found a leftover debugger (`pdb` / `breakpoint()`). It will halt the program when run.",
     "detect": _detect_debugger, "fix": _fix_debugger},
    {"id": "swallowed_exception", "type": "Reliability", "severity": "Medium",
     "msg": "Found an `except` block that only does `pass`. Errors are silently swallowed.",
     "detect": _detect_swallowed_exception, "fix": _fix_swallowed_exception},
    {"id": "bare_except", "type": "Reliability", "severity": "High",
     "msg": "Found a bare `except:`. Catch a specific exception or use `except Exception as e:`.",
     "detect": _detect_bare_except, "fix": _fix_bare_except},
    {"id": "mutable_default", "type": "Reliability", "severity": "Medium",
     "msg": "Found a mutable default argument (`[]`, `{}`). It is shared across calls; use `None` and create it inside.",
     "detect": _detect_mutable_default, "fix": _fix_mutable_defaults},
    {"id": "requests_no_timeout", "type": "Reliability", "severity": "Medium",
     "msg": "Found a `requests` call with no timeout. It can hang forever.",
     "detect": _detect_requests_no_timeout, "fix": _fix_requests_timeout},
    {"id": "open_without_with", "type": "Reliability", "severity": "Medium",
     "msg": "Found `open()` outside a `with` block. The file may never be closed if an error occurs.",
     "detect": _detect_open_without_with, "fix": None},
    {"id": "is_literal", "type": "Correctness", "severity": "Medium",
     "msg": "Found `is` / `is not` used with a string or number literal. Use `==` / `!=` instead.",
     "detect": _detect_is_literal, "fix": _fix_is_literal},
    {"id": "infinite_loop", "type": "Correctness", "severity": "Medium",
     "msg": "Found `while True:` with no `break`/`return` anywhere. This may loop forever.",
     "detect": _detect_infinite_loop, "fix": None},
    {"id": "off_by_one_range", "type": "Correctness", "severity": "Medium",
     "msg": "Found `range(len(x) + 1)`. This iterates one index past the end (likely IndexError).",
     "detect": _detect_off_by_one_range, "fix": None},
    {"id": "eval_exec", "type": "Security", "severity": "High",
     "msg": "Found `eval()` / `exec()`. Running strings as code is dangerous; use `ast.literal_eval` or explicit logic.",
     "detect": _detect_eval_exec, "fix": None},
    {"id": "hardcoded_secret", "type": "Security", "severity": "High",
     "msg": "Found a hardcoded password/token/API key. Load secrets from environment variables instead.",
     "detect": _detect_hardcoded_secret, "fix": _fix_hardcoded_secret},
    {"id": "todo", "type": "Maintainability", "severity": "Medium",
     "msg": "Found TODO/FIXME comments. Unfinished logic can hide bugs or missing cases.",
     "detect": _detect_todo, "fix": None},
]


class GGIAgent:
    """
    GGIAgent runs a small agentic workflow:

    1) PLAN: decide what to look for
    2) ANALYZE: detect issues (heuristics or LLM)
    3) ACT: propose a fix (heuristics or LLM)
    4) TEST: run simple reliability checks
    5) REFLECT: decide whether to apply the fix automatically
    """

    def __init__(self, client: Optional[Any] = None):
        # client should implement: complete(system_prompt: str, user_prompt: str) -> str
        self.client = client
        self.logs: List[Dict[str, str]] = []

    # ----------------------------
    # Public API
    # ----------------------------
    def run(
        self,
        code_snippet: str,
        glitch_description: str = "",
        context_snippets: Optional[List[Tuple[str, str]]] = None,
    ) -> Dict[str, Any]:
        self.logs = []
        glitch_description = (glitch_description or "").strip()
        if glitch_description:
            self._log("PLAN", f"User reported a glitch: {glitch_description}")
        context_snippets = context_snippets or []
        if context_snippets:
            labels = ", ".join(label for label, _ in context_snippets)
            self._log("PLAN", f"Using {len(context_snippets)} retrieved project snippet(s) as context: {labels}")
        self._log("PLAN", "Planning a quick scan + fix proposal workflow.")

        issues = self.analyze(code_snippet, glitch_description, context_snippets)
        self._log("ANALYZE", f"Found {len(issues)} issue(s).")

        fixed_code = self.propose_fix(code_snippet, issues, glitch_description, context_snippets)
        if fixed_code.strip() == "":
            self._log("ACT", "No fix produced (refused, error, or empty output).")

        risk = assess_risk(original_code=code_snippet, fixed_code=fixed_code, issues=issues)
        self._log("TEST", f"Risk assessed as {risk.get('level', 'unknown')} (score={risk.get('score', '-')}).")

        if risk.get("should_autofix"):
            self._log("REFLECT", "Fix appears safe enough to auto-apply under current policy.")
        else:
            self._log("REFLECT", "Fix is not safe enough to auto-apply. Human review recommended.")

        return {
            "issues": issues,
            "fixed_code": fixed_code,
            "risk": risk,
            "logs": self.logs,
        }

    # ----------------------------
    # Workflow steps
    # ----------------------------
    def analyze(
        self,
        code_snippet: str,
        glitch_description: str = "",
        context_snippets: Optional[List[Tuple[str, str]]] = None,
    ) -> List[Dict[str, str]]:
        if not self._can_call_llm():
            self._log("ANALYZE", "Using heuristic analyzer (offline mode).")
            return self._heuristic_analyze(code_snippet, glitch_description)

        self._log("ANALYZE", "Using LLM analyzer.")

        # Load prompt templates from prompts/ folder
        system_prompt = _load_prompt("analyzer_system.txt")
        user_template = _load_prompt("analyzer_user.txt")
        user_prompt = (
            user_template.replace("{{GLITCH}}", self._glitch_text(glitch_description))
            .replace("{{CONTEXT}}", self._context_text(context_snippets))
            .replace("{{CODE}}", code_snippet)
        )

        # UPDATED: Added exception handling for API errors/rate limits
        try:
            raw = self.client.complete(system_prompt=system_prompt, user_prompt=user_prompt)
        except Exception as e:
            self._log("ANALYZE", f"API Error: {str(e)}. Falling back to heuristics.")
            return self._heuristic_analyze(code_snippet, glitch_description)

        issues = self._parse_json_array_of_issues(raw)

        if issues is None:
            self._log("ANALYZE", "LLM output was not parseable JSON. Falling back to heuristics.")
            return self._heuristic_analyze(code_snippet, glitch_description)

        return issues

    def propose_fix(
        self,
        code_snippet: str,
        issues: List[Dict[str, str]],
        glitch_description: str = "",
        context_snippets: Optional[List[Tuple[str, str]]] = None,
    ) -> str:
        if not issues:
            self._log("ACT", "No issues, returning original code unchanged.")
            return code_snippet

        if not self._can_call_llm():
            self._log("ACT", "Using heuristic fixer (offline mode).")
            return self._heuristic_fix(code_snippet, issues)

        self._log("ACT", "Using LLM fixer.")

        # Load prompt templates from prompts/ folder
        system_prompt = _load_prompt("fixer_system.txt")
        user_template = _load_prompt("fixer_user.txt")
        user_prompt = (
            user_template.replace("{{ISSUES}}", json.dumps(issues))
            .replace("{{GLITCH}}", self._glitch_text(glitch_description))
            .replace("{{CONTEXT}}", self._context_text(context_snippets))
            .replace("{{CODE}}", code_snippet)
        )

        # UPDATED: Added exception handling for API errors/rate limits
        try:
            raw = self.client.complete(system_prompt=system_prompt, user_prompt=user_prompt)
        except Exception as e:
            self._log("ACT", f"API Error: {str(e)}. Falling back to heuristic fixer.")
            return self._heuristic_fix(code_snippet, issues)

        cleaned = self._strip_code_fences(raw).strip()

        if not cleaned:
            self._log("ACT", "LLM returned empty output. Falling back to heuristic fixer.")
            return self._heuristic_fix(code_snippet, issues)

        return cleaned

    # ----------------------------
    # Heuristic analyzer/fixer
    # ----------------------------
    @staticmethod
    def _glitch_text(glitch_description: str) -> str:
        text = (glitch_description or "").strip()
        return text if text else "(none provided)"

    @staticmethod
    def _context_text(context_snippets: Optional[List[Tuple[str, str]]], max_chars: int = 1500) -> str:
        """Format retrieved snippets for a prompt, truncating long ones."""
        if not context_snippets:
            return "(none retrieved)"
        parts = []
        for label, text in context_snippets:
            text = text.strip()
            if len(text) > max_chars:
                text = text[:max_chars] + "\n... (truncated)"
            parts.append(f"[{label}]\n{text}")
        return "\n\n".join(parts)

    def _heuristic_analyze(self, code: str, glitch_description: str = "") -> List[Dict[str, str]]:
        issues: List[Dict[str, str]] = []
        glitch_description = (glitch_description or "").strip()
        if glitch_description:
            # Offline mode cannot reason about the report, but it is surfaced so it is not lost.
            # Severity "Info" is deliberately not scored by the risk assessor.
            issues.append(
                {
                    "type": "User Report",
                    "severity": "Info",
                    "msg": f"Reported glitch: {glitch_description} (offline mode cannot diagnose this; use Gemini mode or review manually).",
                    "rule": "user_report",
                }
            )
        for rule in HEURISTIC_RULES:
            if rule["detect"](code):
                issues.append(
                    {
                        "type": rule["type"],
                        "severity": rule["severity"],
                        "msg": rule["msg"],
                        "rule": rule["id"],
                    }
                )
        return issues

    def _heuristic_fix(self, code: str, issues: List[Dict[str, str]]) -> str:
        # Heuristic issues carry a "rule" id. LLM issues do not, so for those we run
        # every fixer whose rule shares the issue's type (each fixer is a no-op if
        # its pattern is absent).
        rule_ids = {i["rule"] for i in issues if i.get("rule")}
        untagged_types = {i.get("type") for i in issues if not i.get("rule")}

        fixed = code
        for rule in HEURISTIC_RULES:
            if rule["fix"] is None:
                continue
            if rule["id"] in rule_ids or rule["type"] in untagged_types:
                fixed = rule["fix"](fixed)
        return fixed

    # ----------------------------
    # Parsing + utilities
    # ----------------------------
    def _parse_json_array_of_issues(self, text: str) -> Optional[List[Dict[str, str]]]:
        text = text.strip()
        parsed = self._try_json_loads(text)
        if isinstance(parsed, list):
            return self._normalize_issues(parsed)

        array_str = self._extract_first_json_array(text)
        if array_str:
            parsed2 = self._try_json_loads(array_str)
            if isinstance(parsed2, list):
                return self._normalize_issues(parsed2)

        return None

    def _normalize_issues(self, arr: List[Any]) -> List[Dict[str, str]]:
        issues: List[Dict[str, str]] = []
        for item in arr:
            if not isinstance(item, dict):
                continue
            issues.append(
                {
                    "type": str(item.get("type", "Issue")),
                    "severity": str(item.get("severity", "Unknown")),
                    "msg": str(item.get("msg", "")).strip(),
                }
            )
        return issues

    def _try_json_loads(self, s: str) -> Any:
        try:
            return json.loads(s)
        except Exception:
            return None

    def _extract_first_json_array(self, s: str) -> Optional[str]:
        start = s.find("[")
        if start == -1:
            return None
        depth = 0
        for i in range(start, len(s)):
            if s[i] == "[":
                depth += 1
            elif s[i] == "]":
                depth -= 1
                if depth == 0:
                    return s[start : i + 1]
        return None

    def _strip_code_fences(self, text: str) -> str:
        text = text.strip()
        match = re.search(r"```(?:python)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1)
        return text

    def _can_call_llm(self) -> bool:
        return self.client is not None and hasattr(self.client, "complete")

    def _log(self, step: str, message: str) -> None:
        self.logs.append({"step": step, "message": message})
