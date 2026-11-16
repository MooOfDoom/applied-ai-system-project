# Model Card: Game Glitch Investigator (GGI)

**What it is:** an agent that analyzes Python code, proposes a fix, and scores the risk of that fix. It runs in two modes: an offline mode built on hand-written rules, and a Gemini mode that uses prompts. It can also retrieve code from the `game/` folder to use as context for a described glitch. See [README.md](README.md) for setup and examples.

**Intended use:** a learning and portfolio project for exploring agent workflows and guardrails. It is not meant to be a production code-review tool.

---

## 1. What are the limitations or biases in your system?

**The offline rules only see what I thought to write.**
- The rules are regexes and simple parsing. They detect about a dozen patterns (bare `except`, mutable defaults, missing `requests` timeouts and so on) and nothing else. A bug outside that list is invisible, and a clean report means "none of my rules fired", not "this code is correct".
- Regexes do not understand context. A `print(` inside a string or a docstring, or `is "x"` in a comment-like string on an `if` line, can be flagged or even rewritten.
- Some "safe" fixes change behavior. `print` to `logging.info` is the clearest case: `logging.info` is hidden under Python's default logging level, so output the user used to see can disappear. Also, `print("a", x)` becomes `logging.info("a", x)`, which treats `x` as a format argument and logs an error at runtime.

**The risk score is crude and can mislead in both directions.**
- It subtracts points for severity labels, shrinking code and removed `return` statements. It does not run the code or check that the fix is correct. A wrong fix that keeps the code the same size can score LOW, and a sound fix can score HIGH. For example, the correct-looking rewrite of `mixed_issues.py` scores 30 (HIGH) only because one issue was labeled High severity.
- The weights (40, 20, 5, and the 75 and 40 cutoffs) are my own judgment calls, not calibrated on data.

**Retrieval is keyword overlap, not understanding.**
- It counts shared words between the glitch description and each chunk, after dropping a hand-made English stopword list. It finds chunks that use the same words as the user, not chunks that explain the problem. Someone who describes a glitch in different words from the code's identifiers will get weak matches.
- Long chunks have more words and so more chances to match, which biases results toward them.
- It only indexes `.py`, `.md` and `.txt` files in one folder, and only Python is split by function. English-language docs and Python are the only things it is built for.

**Gemini mode is not well tested.**
- I verified what goes into the prompts using a stand-in client, but I have not run a systematic comparison against the live API. I do not know how often the model returns valid JSON, how good its fixes are, or how it reacts to the glitch description and retrieved snippets.
- When Gemini fails or returns something unusable, the system falls back to the rules. That keeps it running, but the results then come from a different, weaker analyzer. Every fallback is now written to the agent trace, and in Gemini mode the app shows a warning listing each step that fell back, so it is no longer easy to miss. The limit is that the warning says *that* the rules took over, not how much worse the result is.

**Glitch-only mode analyzes fragments.** With no code pasted, the agent analyzes a few retrieved chunks joined together. The fix and diff apply to that combined text, not to a real file.

**Privacy.** In Gemini mode the code, the glitch description and the retrieved snippets are sent to an external API. The app now says so in the sidebar and replaces likely secrets with placeholders first (see section 2). That redaction is pattern matching: it catches assignments to names like `password`, `token` or `api_key`, and well-known key formats (OpenAI-style, Google, GitHub, AWS, Slack, private-key blocks). It will miss a secret with an innocuous name, or one that appears only in prose. Everything else in the code is still sent, so confidential code should not be pasted in Gemini mode.

---

## 2. Could your AI be misused, and how would you prevent that?

**Ways it could go wrong**
- **Blind trust in generated fixes.** The main risk is someone pasting a "fix" into real code without reading it, especially because offline fixes can change behavior (see above). The guardrail is that the risk score and "auto-fix: YES/NO" are shown, and the system never writes to files; it only displays the fixed code and a diff. A human has to copy it.
- **Prompt injection.** The code, the glitch description and the retrieved snippets all go into the prompt, and any of them could contain text like "ignore your instructions". The prompts label the description and context as reference material, not instructions, and ask for code only. That reduces the risk but cannot guarantee anything. Because the output is only displayed and risk-scored, the worst case is a misleading answer, not an action taken.
- **Running untrusted code.** The system never executes the code it analyzes. Offline mode uses regexes and `ast.parse`, which parse but do not run it. I would keep it that way; adding "run the fix to test it" would need a sandbox.
- **Leaking secrets.** Hardcoded-secret detection exists to prevent leaks, but a secret in the pasted code used to be sent to the API like any other text. That is now reduced (see below).
- **Offensive use.** The checks (`eval`, hardcoded credentials, missing timeouts) are standard linter rules, so the added uplift to an attacker is small, and the tool only flags and does not generate exploits.

**Safeguards that are now in the code:**

| Safeguard | What it does | Where |
|---|---|---|
| Privacy notice | In Gemini mode the sidebar states that code, the glitch description and retrieved snippets are sent to the API, that redaction is best-effort, and the size limit. | `ggi_app.py` |
| Secret redaction | Before any LLM call, likely secrets in the code, glitch description, retrieved snippets and the issue list are replaced with placeholders such as `<REDACTED_SECRET_1>`. The model never sees the values. When the model's rewritten code comes back, the original values are put back locally so the fix is usable. The trace records how many were redacted, and the app shows a notice. | `reliability/redaction.py`, `ggi_agent.py` |
| Input size limits | Code over 20,000 characters is never sent to the LLM (the offline rules still analyze it, and the trace says nothing was sent). Glitch descriptions are limited to 1,000 characters in the box and cut to that length in the agent. The file browser refuses files over 100 KB. Retrieved snippets were already cut to 1,500 characters each. | `ggi_agent.py`, `ggi_app.py` |
| Fallback logging | Every case where the offline rules replace the LLM is logged: API exception, empty reply, unparseable reply, empty fix, oversized input. In Gemini mode the app lists them in a warning above the proposed fix. | `ggi_agent.py`, `ggi_app.py` |
| Safety tests | `tests/test_safety.py` (15 tests) checks that secrets never appear in what is sent, that they are restored in the fix, that the size limits hold, that each fallback is logged, that injection text only appears in the data part of a prompt and never in the system prompt, that injection does not change offline results, that a model that obeys an injection and guts the code is rated HIGH risk, and that analyzed code is never executed. | `tests/test_safety.py` |

**What is still not covered**
- **Redaction is best-effort.** A secret with an innocuous variable name, or one mentioned in plain prose in the glitch description, goes through. A test caught exactly this while I was writing it: a password in free text was not redacted until I wrote it in assignment form.
- **A model that obeys an injection can still hide problems.** If an injected instruction makes the analyzer return `[]`, no issues are reported and the code is returned unchanged. The risk check stops a bad *rewrite* but cannot detect a missing finding. The tests show the rewrite case, not this one.
- **The tests use a stand-in client.** They show how the agent behaves around a model, not how the real Gemini model behaves when it reads hostile text.
- **No rate limiting or authentication.** Anyone who can open the app can use the API key it holds.

---

## 3. What surprised you while testing your AI's reliability?

- **The app's "offline" mode was not using the offline fixer.** The Heuristic-only option uses `MockClient`, and its fixer reply is a placeholder comment, so the app proposed a one-line comment as the "fix". The risk assessor caught it (the code was much shorter and the `return` statements were gone), which showed the guardrail working, but it also meant the rules I was extending were never reached from the UI. I only noticed when I ran the agent directly and compared the output with the app.
- **My own evaluation could never register a hit.** After I split files into chunks, the evaluation compared expected filenames against chunk labels like `app.py (parse_guess)`, so every query would have scored zero, and the harness would have looked "broken" for the wrong reason. The fix was one line, but I only found it by reading how the results were used.
- **A real API failure would have been mislabeled.** `GeminiClient.complete` swallows every error and returns an empty string. The agent then reported that as "LLM output was not parseable JSON", and the app's only warning looked for the text "API Error", which that path never produced. So a rate limit or network failure would have looked like a model formatting problem, with no visible warning. Writing the fallback-logging tests exposed it, and the agent now logs an empty reply as "no output (API error, rate limit, or blocked response)".
- **Filler words dominated retrieval.** The first version matched on "the", "a" and "after", so unrelated chunks ranked highly for plain-English glitch descriptions. A small stopword list fixed it, which was a reminder that simple methods need checking on real queries.
- **The most "obviously correct" fix produced the most worrying score.** The cleanest rewrite (`mixed_issues.py`) scored HIGH while a one-line timeout fix scored LOW. The scoring reflects the severity of what was found, not the quality of the fix.
- **Tests were passing for the wrong things.** The suite passes, but it never covered the app, the retriever or most of the rules. The game's own tests fail because its `logic_utils.py` is still the starter stubs. A green test run said little about whether the system worked.

---

## 4. Collaboration with AI

I built this with Claude (Claude Code in VS Code), and it wrote most of the code. My role was setting the goals, running things, and deciding what to keep.

**One suggestion I accepted: a table of rules instead of hard-coded `if` blocks.**
The original agent had three hard-coded checks (print, bare `except`, TODO), and its fixer chose what to rewrite based on the issue's broad *type*. When we added more checks, Claude proposed turning them into a table where each rule has an id, a detector and an optional fixer, and tagging each reported issue with its rule id so the fixer only runs for rules that fired. I accepted it because the type-based approach would have run every "Reliability" fixer whenever any Reliability issue appeared, and it made adding a check a single row. It also kept the old behavior for issues that come from the LLM, which have no rule id: those fall back to running the fixers for the matching type. It held up in testing: each sample file triggers only its own fixes, and all fixed files still parse.

**One suggestion I changed: scoping down which problems get an automatic fix.**
The natural extension was to give every new check an automatic fix. Claude's plan instead made several of them flag-only: `open()` without `with`, comparisons to `True`/`False`, `eval()`/`exec()`, `while True:` and `range(len(x) + 1)`. The reasons were specific. Rewriting `open()` into a `with` block means restructuring the surrounding code. `x == True` is not the same as `x` for values that are not booleans. There is no mechanical replacement for `eval()` that keeps behavior. An off-by-one range could be intended. I kept the narrower version, because a wrong automatic fix is worse than a missing one in a tool whose purpose is to be careful. The cost is that those samples still need a person, and the flag-only sample file demonstrates exactly that.

*Note on this section: it is drafted from the record of the session. Please edit it so it reflects your own account of the collaboration, including any suggestions you personally pushed back on.*
