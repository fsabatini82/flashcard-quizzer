# AI Edit Log

**Instructions:** Use this document to track all your interactions with AI assistants during the project. This log will help you reflect on your AI collaboration process and demonstrate your learning journey.

**Project:** Flashcard Quizzer  
**Author:** Fabio Sabatini  
**Date:** 2026-11-07  
**AI tool:** Claude Code, which delegated bounded tasks to worker agents under my direction

## How to Use This Log

For each AI interaction, create a new entry with the following structure:

### Entry Template
```
## [Date] - [Brief Description]

**Context:** What were you trying to accomplish?
**AI Tool Used:** Claude/ChatGPT/Copilot/etc.
**Prompt/Request:** What exactly did you ask the AI?
**AI Response:** Summary of what the AI generated (don't copy entire code blocks)
**Changes Made:** What modifications did you make to the AI's suggestions?
**Reasoning:** Why did you make those changes?
**Outcome:** What was the final result?
**Lessons Learned:** What did you learn from this interaction?
```

## Review Method

Every AI output was reviewed against the categories of
`ai_guidance/code_review_checklist.md`: correctness, code quality, security,
performance, error handling and robustness, integration and compatibility,
testability, and maintainability. I did not rely on the worker's own report;
I had the results re-verified independently:

- re-running pytest, coverage, black, isort, flake8 and mypy;
- comparing all protected files byte for byte against the original repository
  blobs with `cmp`;
- injecting mutants into the source to check that the tests fail when the
  behaviour is broken (entry 6);
- reviewing the code for design issues that tools cannot see, such as interface
  growth and default arguments bound at definition time (entries 3 and 5).

Entries 1-9 below follow the order in which the work happened. All entries use
Claude Code. Entries 1-7 are from 2026-11-07, entries 8-9 from 2026-11-08.

---

## Log Entries

## 2026-11-07 - Scaffolding the starter / environment

**Context:** I needed a local copy of the course starter project (`project/` inside the `cd14602-project-starter` repository) to work in.

**AI Tool Used:** Claude Code

**Prompt/Request:** Clone the starter repository on Windows and set up the `project/starter` folder as the working directory.

**AI Response:** `git clone` failed with `invalid path ...:Zone.Identifier`: some files inside the lesson folders have a colon in their name, which Windows cannot create. Claude then tried a sparse checkout and `git archive` on a partial clone; both also failed. A PowerShell attempt used `Set-Content -AsByteStream`, which does not exist in Windows PowerShell 5.1. Finally it made a bare clone in a temporary directory and extracted only `project/` with `git cat-file blob` for each file, run in Bash so the bytes were copied unchanged. That produced the 21 starter files.

**Changes Made:** None to the final approach. I accepted the bare clone plus `git cat-file blob` extraction.

**Reasoning:** Only `project/` was needed, and extracting blobs directly avoids ever creating the invalid paths. Doing it in Bash avoided the PowerShell 5.1 limitation and kept the file contents byte-safe.

**Outcome:** The working folder contained the 21 starter files. The original blobs remained available in the bare clone, which later let me compare protected files against the originals (entry 2).

**Lessons Learned:**
- When a tool fails, change the approach instead of retrying the same command; three different approaches failed for three different reasons.
- Verify results by listing files instead of trusting that a command finished.
- Keeping the original blobs around is cheap and made later verification possible.

---

## 2026-11-07 - Implementation brief for phases 1-3 (delegated to a worker agent)

**Context:** I wanted the application core (loader, quiz engine, UI, entry point and helpers) built in one delegated task, with quality gates, so that I could review a complete working application.

**AI Tool Used:** Claude Code (delegating to a worker agent)

**Prompt/Request:** A long structured brief. It named the modules: `utils/file_handler.py`, `data_loader.py`, `quiz_engine.py` (a `QuizMode` abstract base class with `SequentialMode`, `RandomMode` and `AdaptiveMode`, a registry-based factory `create_mode`, and a UI-free `QuizSession`), `ui.py` with injectable I/O and ANSI colours, and a thin `main.py` using argparse. It listed the error cases to handle explicitly (missing file, directory, empty file, invalid JSON with line and column, non-UTF-8 file, missing field naming the card position, duplicate fronts), the quality gates (mypy `--strict`, black, isort, flake8, Python 3.10), the extras (`--limit`, `--seed`, `--history-file`, `--export`), a manual verification list, and an instruction to report ambiguities.

**AI Response:** Seven modules, about 1,300 lines in total, including `utils/history.py` and `utils/exporter.py` (with a CSV formula-injection guard), plus two new decks (`server_acronyms` with 14 cards and `git_commands` with 13). black, isort, flake8 and mypy were clean. The worker ran `--help`, a piped session, an adaptive repeat and five error paths by hand. It flagged three ambiguities: `--stats` means an extra per-card table (the basic summary is always shown); accuracy counts attempts (a repeated card counts each time in adaptive mode); and the history update rule (+1 per miss, -1 for a card answered correctly and never missed in the session, with a corrupt history file ignored with a warning and never overwritten).

**Changes Made:**
- I accepted all three ambiguity decisions as proposed.
- The worker had run `isort .` before excluding `.claude/` and silently rewrote four extensionless scripts in `.claude/commands/` (import order only). The worker's own report disclosed this. I compared every protected file with the original blobs using `cmp`, confirmed exactly four changed files, and restored them byte for byte from the original repository.
- `pyproject.toml` now has an isort skip list that excludes `.claude`, `ai_guidance`, `docs` and `venv`.

**Reasoning:** The accepted decisions were sensible defaults and consistent with the specification. The `.claude/` edit was harmless in content but out of scope, and I do not want to rely on "it was only import order": protected paths must stay identical to the originals.

**Outcome:** A working application passing all four quality tools, with the protected files back to their original bytes and the formatter configuration fixed so the problem cannot recur.

**Lessons Learned:**
- State explicitly which paths are read-only, and tell the agent to report rather than silently change anything outside the scope.
- Verify "do not touch" claims mechanically (`cmp` against the originals), not by trusting a summary.
- A brief that lists error cases one by one gets those cases handled; asking for "error handling" in general does not.

---

## 2026-11-07 - Reviewing quiz_engine.py against the checklist

**Context:** `quiz_engine.py` holds the Strategy and Factory code and the scoring logic, so it is the heart of the design. I reviewed it against the checklist before building tests on top of it.

**AI Tool Used:** Claude Code

**Prompt/Request:** This entry is a review, not a generation request: Review of `quiz_engine.py` (written by the worker in entry 2) against `ai_guidance/code_review_checklist.md`, as a reviewer rather than the author.

**AI Response:** Findings of the review. Accepted points: a queue-based `_QueueMode` base keeps `SequentialMode`, `RandomMode` and `AdaptiveMode` very small; `AdaptiveMode` is iterative (no recursion), re-queues a missed card `REINSERT_GAP = 3` positions ahead (or at the end if fewer cards remain) and never re-asks a correct card; the factory registry is case-insensitive and its `ValueError` lists the valid choices. Concerns raised: the worker added an extra abstract method `limit_to()` to the `QuizMode` interface so that `--limit` works, which widens the Strategy interface beyond "select the next card"; and `utils/history.py` imports `SessionStats` from `quiz_engine`, so a helper depends on a domain module.

**Changes Made:** None. I recorded both concerns as accepted trade-offs and documented them in `docs/architecture.md` under "Known trade-offs".

**Reasoning:** The alternative for `limit_to()`, a `LimitedMode` decorator that wraps any mode, would keep the interface smaller but adds a class and indirection for a project of this size. I judged it over-engineering. Moving the statistics dataclasses into a separate module to fix the helper dependency has the same cost-benefit problem.

**Outcome:** The code was kept as written and the two trade-offs are written down, so a reader knows they are conscious choices, not oversights.

**Lessons Learned:**
- AI tends to add convenience hooks to an abstraction when a feature needs one; review explicitly for interface creep.
- A concern does not always require a change. Recording the trade-off and the rejected alternative is a legitimate outcome of a review.

---

## 2026-11-07 - Edge case the AI missed: answer equal to an exit word

**Context:** The review of `ui.py` showed that any input equal to `exit` or `quit` was treated as a quit command. A card whose correct answer is `exit` could therefore never be answered. None of the bundled decks has such a card, so neither the default tests nor manual runs would ever expose it.

**AI Tool Used:** Claude Code

**Prompt/Request:** In the brief for the test-writing worker I included the exact fix: treat the input as quit only if it is an exit word and does not equal the card's expected answer after `normalize_answer`. I asked for tests for both behaviours and told the worker to report any other bug instead of silently fixing it. Excerpt from the brief: *"Fix: treat the input as an exit command only when it is an exit word AND it does not equal the card's expected answer after quiz_engine.normalize_answer. [...] If while writing tests you find ANY other bug in the source, DO NOT silently fix it [...] report it to me in RESULT with file:line, expected vs actual."*

**AI Response:** The fix was applied in `QuizUI.ask`. To prove that the new tests are able to fail, the worker temporarily removed the second condition; five tests failed (two in `test_integration.py` and three in `test_ui.py`). It then restored the condition.

**Changes Made:** The condition in `QuizUI.ask` (a change made by the AI at my direction); new tests for both behaviours: an exit word that equals the answer is scored, and an exit word on a card with a different answer still quits.

**Reasoning:** The defect only appears with unusual decks, which is exactly why a happy-path test suite does not find it. A mutation of the fix (removing the second condition) showed that the tests protect it.

**Outcome:** A card whose answer is `exit` or `quit` can be answered, and `exit` still quits on every other card. This is one of the two post-review modifications to AI-written code (the other is entry 5).

**Lessons Learned:**
- Spec-driven prompts, where I describe the exact behaviour I want, catch what default happy-path tests do not.
- An explicit "report, do not silently fix" rule keeps the decision with the human.

---

## 2026-11-07 - Test-suite generation with exact rubric names

**Context:** I needed a pytest suite that covers the loader, the modes, the UI, history, export and whole sessions, including the test names required by the course rubric.

**AI Tool Used:** Claude Code (worker agent for the tests)

**Prompt/Request:** A brief that specified the exact required test function names (`test_load_valid_flashcards_array`, `test_load_invalid_json`, `test_load_missing_required_field`, `test_quiz_mode_factory`, `test_adaptive_mode_behavior`, `test_full_session`), the scenarios for each file, the rule "`tmp_path`, `monkeypatch` and `capsys` only, no real stdin", and the requirement that the typed tests pass black, isort, flake8 and mypy `--strict`. It also asked for an honest report of first-run failures.

**AI Response:** 269 tests across seven files with 100% line coverage; all tests passed on the first run. The worker reported the problems it hit and fixed itself: its file-writing tool converted `\uXXXX` escapes into literal non-ASCII characters, which made isort emit a charmap warning and skip four test files (fixed by writing the characters back as escapes); the first lint pass found four black reformatting issues, one flake8 E501 and one mypy `func-returns-value` error on a lambda using `or`; it removed inline imports and an unused `Mapping` import. It also reported a discovery: `QuizUI`'s default `input_fn=input` binds the builtin at definition time, so monkeypatching `builtins.input` had no effect (pytest raised "reading from stdin while output is captured"). The worker worked around it with a `FakeStdin` on `sys.stdin`.

**Changes Made:**
- I asked the worker to fix the source (follow-up prompt: *"YES fix ui.py:62: make input_fn `Callable[[str], str] | None = None` and resolve builtins `input` at call time [...] then add one end-to-end test that monkeypatches `builtins.input` and drives main([...])"*): `input_fn` and `print_fn` default to `None` and are resolved when the UI is constructed, plus a new end-to-end test, `test_builtins_input_can_be_monkeypatched`. The suite became 270 tests. This is the second of the two post-review modifications, again made by the AI at my direction.
- I decided that the `--seed` help text should say it only affects random mode.
- I decided to leave the rejection of the bare `.json` export filename as it is; a test documents it.

**Reasoning:** A workaround in the tests would have hidden a real design flaw: an injectable dependency whose default is bound too early is not truly injectable. Fixing the source makes the UI patchable by any caller.

**Outcome:** 270 passing tests and 100% line coverage, with the UI default-argument flaw fixed and the `--seed` behaviour documented in the help text.

**Lessons Learned:**
- Dependency-injection defaults evaluated at definition time are a classic AI pitfall.
- Here the tests exposed a design flaw, not only a bug; the worker's honest report of the workaround is what let me make the decision.
- Asking for exact test names and scenarios made the rubric easy to verify.

---

## 2026-11-07 - Not trusting 100% coverage (mutation sanity check)

**Context:** The worker reported 100% line coverage (510 statements, 0 missed). Coverage counts executed lines, not assertions, so it does not prove that the tests would notice a bug.

**AI Tool Used:** Claude Code

**Prompt/Request:** After the worker's report I re-ran pytest, black, isort, flake8 and mypy independently, and then injected two small bugs (mutants) into `quiz_engine.py` to check that the suite fails, restoring the file afterwards and verifying the restore.

**AI Response:** All tools passed independently. Mutant 1 inverted the adaptive re-queue condition (`if (not correct) or card in self._queue`): the suite failed (1 failed, 146 passed with `-x`). Mutant 2 removed `casefold()` from `normalize_answer`: the suite failed (1 failed, 124 passed with `-x`). The source was restored byte for byte, verified with `cmp`, and the suite returned to 270 passed.

**Changes Made:** None to the code (the mutants were temporary and reverted).

**Reasoning:** One mutant in the adaptive logic and one in answer normalisation cover the two behaviours users would notice most: repeating missed cards and case-insensitive matching.

**Outcome:** Evidence that the suite detects broken behaviour in the two most important functions, beyond the coverage number.

**Lessons Learned:**
- Coverage is a floor, not a measure of test quality.
- Mutation checks by hand are a cheap way to test the tests. Two mutants do not prove the whole suite is strong; they only show that these two behaviours are protected.

---

## 2026-11-07 - Prompt refinement between iterations

**Context:** After the first delegation produced an out-of-scope edit (entry 2), I compared how the two briefs were written to see what made the second one work better.

**AI Tool Used:** Claude Code

**Prompt/Request:** Brief 1 (implementation) listed "do not touch `.claude/`", but did not say what to do when a tool would touch it, and had no "report instead of fixing" rule. Brief 2 (tests) added: exact test names per file; "report any other bug with file:line, expected versus actual, do not silently fix"; "never run formatters on `.claude`"; a required honest report of first-run failures ("I need these honestly for the log"); and measurable targets (at least 90% coverage, exact tool outputs).

**AI Response:** Brief 2 produced zero scope violations (I verified the protected files with `cmp`), surfaced three findings with file:line, and reported its own mistakes (the escape-conversion problem and the lint failures from entry 5).

**Changes Made:** Brief 2 was written with the additions above; brief 1 was not changed retroactively (its out-of-scope edit was repaired as described in entry 2).

**Reasoning:** Brief 1 told the agent what not to touch but not how to behave when a tool wanted to; brief 2 closed that gap and made success checkable.

**Outcome:** Cleaner output and an honest, reviewable report from the second iteration.

**Lessons Learned:**
- Measurable acceptance criteria plus explicit escalation rules produce better output than a list of prohibitions.
- Asking the agent to report its own failures is what makes a log like this one possible.

---

## 2026-11-08 - Correcting the AI-written documentation

**Context:** A worker agent drafted the README, `docs/architecture.md`, this log and the report. Before publishing, I reviewed the drafts for accuracy and voice.

**AI Tool Used:** Claude Code

**Prompt/Request:** After reading the drafts and playing the app myself, I asked (translated from Italian): *"All files and comments must be in direct form, as if written by me. Ownership must be clear, especially in decisions and reasoning. The tool used for a mechanical or deterministic action is a different matter."* I also asked for the repository URL in the README.

**AI Response:** The drafts were accurate on facts but mixed voices: some passages described the work in the third person ("the orchestrating session"), while others attributed mechanical tool runs to me personally. They also said Windows colours had never been checked in a real terminal, which was true when written but no longer true after my manual session.

**Changes Made:**
- Goals, decisions and reasoning are now stated in the first person; mechanical actions (running tools, comparing files, injecting mutants) are attributed to Claude Code acting on my instructions. Findings that came out of the AI's review are described as such, not as my own discoveries.
- The README, report, architecture notes and this log now record my manual adaptive session in Windows Terminal (colours, the repeated card and the summary were correct). I later pressed Ctrl+C by hand as well, and it stopped the quiz cleanly; the documents record that too.
- Added a "Getting the code" section with the repository URL.
- The worker could not save `docs/report.md` itself (its file-writing tool refused report files) and returned the text instead of working around the block; the text was saved unchanged before these edits.

**Reasoning:** The documents are mine and must state my decisions directly, but they must not claim checks I did not run or discoveries I did not make. The manual test changed a fact, so every place that stated the old fact had to change with it.

**Outcome:** Consistent first-person documents whose factual claims match what was actually done.

**Lessons Learned:**
- AI-written documentation needs the same review as AI-written code: check every factual claim against what really happened.
- When a new fact arrives (here, a manual test), search for every place the old fact was stated.

---

## 2026-11-08 - Final review against the assignment checklist

**Context:** Before submitting, I wanted an independent end-to-end review of exactly what the repository contains, against the instructions and the rubric.

**AI Tool Used:** Claude Code, switched to a stronger model (Claude Opus) for this review

**Prompt/Request:** (translated from Italian) *"Now that we are almost at the end, I want a review by Opus. Verify everything we are delivering in the repo. The code works, and we have the screenshots we can attach in the docs, together with the coverage report."*, followed by the full assignment instructions.

**AI Response:** The review started from a fresh clone of the GitHub repository, so it checked what is actually delivered: 270 tests passed, coverage 100%, black, isort, flake8 and mypy clean, all six required test names present. It then reported four findings:
1. Ctrl+C was handled only while a question was waiting for input. Pressed during deck loading, the summary or the history/export writes, it would end in a traceback, against the requirement to quit gracefully without errors.
2. The report lacked two sections of the template ("Software Engineering Insights" and "Appendix C: Additional Resources"), and its header lines had no line breaks, so they rendered on a single line on GitHub.
3. Test, statement and line counts in the README and report were stale after the changes.
4. The screenshots of my manual session were not in the repository.

**Changes Made:**
- `main()` now runs the application inside a `KeyboardInterrupt` guard that prints "Interrupted." and returns exit code 130; Ctrl+C during a question still shows the summary and returns 0. New test: `test_keyboard_interrupt_outside_a_question_exits_quietly`.
- Added the two missing report sections, fixed the header line breaks, and trimmed the report back under 1,500 words.
- Updated the numbers (271 tests, 516 statements, 100% coverage) and regenerated `docs/coverage_report.txt`.
- Added the screenshots under `docs/screenshots/` and linked them from the README and the report.

**Reasoning:** The specification says Ctrl+C must quit gracefully, without qualifying when it is pressed, so a guard at the outermost level is the correct fix rather than more local handlers. The template and the word limit are part of the assessment.

**Outcome:** 271 passing tests, 100% coverage, all linters clean, a complete report and screenshots in the repository.

**Lessons Learned:**
- Tests confirm the behaviour I asked for, not the behaviour the specification asks for; a line-by-line re-read of the specification at the end found a gap that 270 tests had not.
- Review documentation with the same care as code.
- Reviewing a fresh clone, not the working folder, verifies what is really delivered.

---

## Tips for Effective AI Collaboration

### 1. Be Specific in Your Requests
- ❌ "Write a function"
- ✅ "Write a function that validates email addresses using regex, returns a boolean, and includes proper error handling"

### 2. Provide Context
- Include relevant code snippets
- Explain the larger goal
- Mention any constraints or requirements

### 3. Review and Understand
- Never copy AI code without understanding it
- Ask for explanations of complex logic
- Test the code before accepting it

### 4. Iterate and Refine
- Use follow-up questions to improve the code
- Ask for alternative implementations
- Request code reviews and suggestions

### 5. Document Your Process
- Keep detailed notes in this log
- Explain your decision-making process
- Track what works and what doesn't

## Common AI Collaboration Patterns

### Code Generation
- Initial implementation of classes/functions
- Boilerplate code creation
- Test case generation

### Code Review
- Ask AI to review your code for issues
- Request suggestions for improvements
- Get feedback on code structure

### Problem Solving
- Debugging help
- Algorithm suggestions
- Architecture advice

### Learning and Explanation
- Ask for explanations of complex concepts
- Request examples of design patterns
- Get guidance on best practices

## Reflection Questions

1. **What types of tasks did AI help with most effectively?**
   Generating a complete, working module set from a structured brief (entry 2) and writing a large test suite to a precise list of names and scenarios (entry 5). Both came back lint-clean and passing. The AI also did well at explaining its own ambiguities and reporting its failures when asked to.

2. **Where did you need to make the most modifications to AI suggestions?**
   In `ui.py`, plus the final Ctrl+C guard in `main.py` (entry 9). Two issues were found after review in `ui.py` and both were fixed in that file by the AI at my direction: an answer equal to an exit word was treated as quit (entry 4), and the `input`/`print` defaults were bound at definition time (entry 5). Outside the code, the only correction was restoring four files in `.claude/commands/` that a formatter had changed (entry 2).

3. **What patterns did you notice in AI strengths and weaknesses?**
   Strengths: consistent structure, docstrings and type hints, quality tools passing, and honest reporting when asked. Weaknesses: edge cases that no default test would expose (entry 4), design details such as default arguments bound too early (entry 5), convenience hooks added to an abstraction (`limit_to()`, entry 3), and acting slightly beyond scope when a tool allowed it (entry 2).

4. **How did your prompting technique improve over time?**
   The briefs moved from listing prohibitions to stating measurable acceptance criteria, exact names, read-only paths and an explicit "report, do not silently fix" rule (entry 7). The second brief produced no scope violations.

5. **What would you do differently in future AI collaborations?**
   State the read-only paths and the escalation rule in the very first brief. Ask for a self-review of edge cases (such as inputs that collide with command words) before tests are written. Add a mutation check to the acceptance criteria instead of running it only afterwards. Test interactively in a real terminal earlier: I only played a full adaptive session in Windows Terminal at the end (colours, repeated card, summary and Ctrl+C were correct).

## Summary Statistics

Line counts were computed with `wc -l` (physical lines, including blank lines, comments and docstrings).

- **Total AI interactions:** 9 logged (entries 1-9).
- **Lines of AI-generated code used:** 4,286 Python lines: 1,335 in the application (`main.py`, `data_loader.py`, `quiz_engine.py`, `ui.py`, `utils/*.py`) and 2,951 in the tests (`tests/*.py`). All of the code under review was written by the AI; I did not hand-write any of it. The four bundled decks and the documentation are not counted.
- **Lines of AI-generated code modified after review:** three small areas, all changed by the AI at my direction: the top-level Ctrl+C guard in `main.py` (entry 9) and two areas of `ui.py`: the exit-word condition in `QuizUI.ask` (entry 4) and the default-argument resolution for `input_fn` and `print_fn` in `QuizUI.__init__` (entry 5), with their docstrings. Together these are a few dozen lines out of the 1,335 application lines. In every case I made the decision and the AI made the edit.
- **Most helpful AI interaction:** The test-suite generation (entry 5): it delivered 270 passing tests and its honest report exposed the late-binding design flaw.
- **Most challenging AI interaction:** The implementation brief (entry 2): the worker went out of scope with a formatter, and I had to detect and undo it mechanically.
- **Biggest lesson learned:** Measurable acceptance criteria plus explicit escalation rules ("report, do not silently fix") give better results than prohibitions, and every claim should be verified independently (coverage, protected files) instead of trusted.

---

**Note:** This log is a required component of your final project report. Be thorough and honest in your documentation to demonstrate your learning process and AI collaboration skills.
