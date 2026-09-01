# Learning Transfer Demo — cross-question generalization

Teach **Q-08**, then answer a *different, never-taught* question **Q-04** of the same type. The gain comes only from the transferred lesson.

```
================================================================================
CROSS-QUESTION LEARNING TRANSFER DEMO
================================================================================

TAUGHT question A : Q-08  [release_delay]
  Walk through the complete causal chain of the v2.1 delay, correcting any wrong theories.

TEST  question B : Q-04  [release_delay]   << never taught
  The postmortem says v2.1 was delayed by a QA backlog and a load spike. Is that accurate?

--------------------------------------------------------------------------------
STEP 1 — Teach A (Q-08): AI answers, expert gives ground truth, system distils a lesson
--------------------------------------------------------------------------------
A V1 similarity to expert: 0.93

>>> LESSON LEARNED  LE-001  (type=strategy, source=Q-08, trigger=release_delay)
    First consult the incident log, the migration script, and the rollback commit to establish the factual chain; then cross‑check each step against the official incident report, and avoid inserting unverified ticket IDs or service names that are not documented.

--------------------------------------------------------------------------------
STEP 2 — Answer B (Q-04) — NEVER taught. Show the Q-08 lesson gets used.
--------------------------------------------------------------------------------
Is B's own answer memorised?  NO   (NO => any gain is transfer)

Lessons retrieved for B: 1
  - LE-001 (from Q-08, score 1.0, entity_match=True)

B WITHOUT the lesson (cold):  similarity=0.94  root_cause=0.9  coverage=0.33
  answer: No. The evidence shows the QA regression backlog (TICKET-130) was not on the critical path for v2.1, and the load‑spike explanation in the postmortem was later disproved – the real issue was migration 0042 adding a non‑null column without a default, not a traffic surge.

B WITH the Q-08 lesson (warm): similarity=0.94  root_cause=1.0  coverage=1.00
  answer: No, that statement is not accurate. The delay of v2.1 was caused by the migration 0042 issue that broke payment writes, not by the QA regression backlog (which was not on the critical path) or a genuine load spike (the load spike was a mistaken hypothesis).

>>> TRANSFER GAIN on the never-taught question: +0.01 similarity  (0.94 -> 0.94)
    Expert answer for B (reference):
    No — both are wrong. The QA regression backlog (TICKET-130) was real but off the critical path, and there was no load spike; that was an incorrect early hypothesis in the postmortem. The actual delay was caused by migration 0042 breaking payment writes (INC-9); v2.1 was held until the migration was reverted (COMMIT-a1b2). Both the postmortem and the release-notes wiki are misleading.

Why this is real learning: B was never taught, its answer is not stored, yet the
strategy the system learned from Q-08 measurably improved its answer to Q-04.
```
