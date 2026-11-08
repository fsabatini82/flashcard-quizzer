# AI-Assisted Development Project Report

**Student Name:** Fabio Sabatini
**Project Title:** Flashcard Quizzer
**Date:** 2026-11-07

## Executive Summary

I built Flashcard Quizzer, a command-line application that loads flashcards from a JSON deck and quizzes the user in sequential, random or adaptive mode. It validates decks, gives coloured feedback, supports early exit, and ends with a summary table. Extras: a history file that lets adaptive mode remember weak cards across sessions, JSON and CSV export, `--limit`, `--seed` and `--stats`.

I used Claude Code as an orchestrating session that delegated bounded tasks (implementation, tests, documentation) to worker agents. The AI wrote all of the code. The briefs, the review and the verification runs were done in that orchestrating session under my direction; I set the goals and approved each design decision.

## Project Overview

### Problem Statement
Revising terms from a plain list is passive. Learners need a tool that asks questions, checks answers forgivingly, and returns to the cards they miss.

### Solution Approach
The application uses only the Python standard library (3.10+). `quiz_engine.py` has no I/O, `ui.py` owns all console I/O, and `main.py` only wires things together. Question ordering uses the Strategy pattern and mode creation uses a registry-based Factory. Both serve real purposes: there are three genuinely different selection algorithms, and adding a fourth, such as spaced repetition, takes one subclass and one registry line; a test registers a throwaway mode to show this. See [architecture.md](architecture.md).

### Final Features
- [x] Sequential, random and adaptive modes (`--mode`)
- [x] Deck validation for both JSON layouts with specific errors
- [x] Coloured feedback, exit handling, summary table, `--stats`
- [x] History-backed adaptive mode (`--history-file`)
- [x] JSON and CSV export (`--export`)
- [x] `--limit` and `--seed`

## AI Collaboration Experience

### AI Tools Used
- [x] Claude (Claude Code, orchestrating worker agents)
- [ ] GitHub Copilot, ChatGPT, other (not used)

### Collaboration Workflow
1. **Requests.** Each brief stated the goal, modules, explicit error cases, quality gates, read-only paths, and what to report. Tasks were set-up, core and extras, tests, and documentation.
2. **Review and validation.** Every output was checked against the review checklist categories (correctness, quality, security, performance, robustness, integration, testability, maintainability). I did not accept worker summaries: I re-ran pytest and all linters, compared protected files with the originals using `cmp`, and injected mutants.
3. **Refinement.** Decisions that changed the code went back to a worker as precise instructions.

### Most Valuable AI Interactions

#### Example 1: Implementation brief and an out-of-scope edit
**Context:** I needed the application core in one task.
**AI Prompt:** A structured brief: modules, error cases, quality gates, extras, "report ambiguities".
**AI Response:** Seven modules of about 1,300 lines, two new decks, clean tool output, and three flagged ambiguities (meaning of `--stats`, accuracy counting, the history update rule).
**Your Changes:** I accepted the ambiguity choices. The worker had also run `isort .` and silently reordered imports in four scripts under `.claude/commands/`. I spotted this in its report, confirmed it with `cmp`, restored the files byte for byte, and excluded those paths in `pyproject.toml`.
**Outcome:** A working application, and a rule: name read-only paths.

#### Example 2: An edge case no default test would find
**Context:** Reading `ui.py`, I saw that any input equal to `exit` quit the quiz, so a card with the answer `exit` could never be answered.
**AI Prompt:** The test brief stated the rule: quit only if the input is an exit word and differs from the card's expected answer, with tests for both behaviours.
**AI Response:** The fix in `QuizUI.ask`. To prove the tests bite, the worker removed the second condition; five tests failed; it restored the code.
**Your Changes:** None beyond the specification.
**Outcome:** Fixed and protected by tests.

#### Example 3: Tests exposing a design flaw
**Context:** The worker produced 269 tests; all passed first time.
**AI Prompt:** Exact test names and scenarios, no real stdin, linter-clean typed tests, and an honest account of first-run failures.
**AI Response:** It reported that `QuizUI`'s default `input_fn=input` binds the builtin at definition time, so patching `builtins.input` had no effect, and used a fake `sys.stdin` as a workaround.
**Your Changes:** I asked for the source to be fixed instead: defaults are now `None`, resolved at construction, plus an end-to-end test.
**Outcome:** A genuinely injectable UI.

### Challenges with AI Collaboration
The AI handled happy paths well but missed an unusual input, bound a default argument too early, added a hook to an abstraction, and acted beyond its scope when a tool allowed it.
## Software Engineering Practices

### Code Quality Measures
- [x] Code formatting (Black, isort)
- [x] Linting (flake8, mypy strict)
- [x] Type hints
- [x] Documentation (docstrings, README, architecture notes)
- [x] Error handling (one exception type per layer)

### Testing Strategy
There are 270 tests in seven files: unit tests per module, parametrised edge cases, and integration tests that run whole sessions through `main()` with scripted input, using only `tmp_path`, `monkeypatch` and `capsys`. Line coverage is 100%. Ctrl+C and end-of-input handling are tested with simulated `KeyboardInterrupt` and `EOFError`. Because coverage counts executed lines, not assertions, I also injected two bugs into `quiz_engine.py` (an inverted adaptive re-queue condition, a removed `casefold()`); both were caught. The tests were written after the code.

### Design Patterns Used
- **Strategy:** `QuizMode` and its three subclasses decide the next card; `QuizSession` does not know which one it holds.
- **Factory:** `create_mode()` builds a mode from a registry, validates the name and applies `--limit`.

### Code Structure and Organization
Seven modules with single responsibilities: loading, engine, UI, entry point, and helpers for files, history and export. The engine never imports the UI.

## Technical Challenges and Solutions

### Challenge 1: Cloning the starter on Windows
**Problem:** `git clone` failed on Windows because some lesson files have a colon in their name; sparse checkout, `git archive` and a PowerShell attempt also failed.
**Solution:** A bare clone in a temporary directory, then extraction of only `project/` with `git cat-file blob` per file (21 files).
**AI Involvement:** Claude changed approach after each failure.
**Lessons Learned:** When a tool fails, change the approach, and verify the result.

### Challenge 2: Interface creep
**Problem:** `--limit` led the worker to add `limit_to()` to the `QuizMode` interface.
**Solution:** I kept it and documented the trade-off; a `LimitedMode` decorator seemed over-engineered here.
**AI Involvement:** The AI proposed the hook; I judged it in review.
**Lessons Learned:** Review for interface creep.

## Code Quality Analysis

### Metrics
- Lines of code: 1,315 in the application and 2,932 in the tests (`wc -l`, including blanks and docstrings)
- Test coverage: 100% (510 statements, 270 passing tests)
- Number of functions/classes: 16 classes and 68 functions or methods in the application (Python `ast` count)
- Linting score: black, isort, flake8 and mypy (strict) report no issues

### Self-Assessment
- **Code Readability:** 4 - Small modules and docstrings; some error handling is repetitive.
- **Code Maintainability:** 4 - New modes are cheap; known trade-offs keep it from a 5.
- **Test Quality:** 4 - Full coverage and two caught mutants, but only two were tried and the tests came after the code.
- **Documentation:** 4 - README, architecture notes, AI log and docstrings are complete; diagrams are not tool-checked.

## Learning Outcomes

### Technical Skills Developed
Strategy and Factory for a real variation point; atomic file writes; strict typing; pytest fixtures; injectable I/O.

### AI Collaboration Skills
Briefs with measurable acceptance criteria and read-only paths; requiring agents to report, not silently fix; independent verification. Mutation checks test the tests.

## Reflection

### What Worked Well
Precise briefs and honest failure reports let me decide quickly, and verification caught the one scope violation. I am most pleased with the engine/UI separation, which made everything testable without a terminal.

### What Could Be Improved
- State read-only paths and escalation rules in the first brief.
- Request an edge-case self-review before tests are written.
- Windows colours were only logic-tested, not checked in an interactive terminal, and Ctrl+C was verified with simulated interrupts, not by pressing the keys.
- A `LimitedMode` decorator would shrink the Strategy interface.

### Future Enhancements
- A spaced-repetition mode as a new subclass.
- Unicode terminal tests and real-user testing on all three operating systems.

## Conclusion

AI-assisted development worked best when I acted as specifier and reviewer. The AI produced about 4,200 lines quickly; the review was only worth something because it included checks that did not rely on the AI's word. I will keep using measurable acceptance criteria, explicit scope rules and mutation checks.

## Appendices

### Appendix A: AI Interaction Log
[ai_edit_log.md](ai_edit_log.md) holds seven entries, including the scope violation (2), the exit-word edge case (4) and the late-binding flaw (5).

### Appendix B: Code Statistics
See [coverage_report.txt](coverage_report.txt).
