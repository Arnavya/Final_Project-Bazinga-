"""Generate the synthetic knowledge sources and gold scenarios.

Deterministic (no randomness, no LLM) so the dataset is reproducible. The world is a
small fictional company "Acme". It is intentionally REALISTIC and IMPERFECT:

  * GAPS    — the complete answer (resolution, prevention, ETA, mitigation, escalation)
              often is NOT written in any source; only the human expert knows it.
  * FALSE   — some documents are wrong/misleading (a postmortem blaming a "load spike",
              a stale wiki owner, an off-critical-path red herring).
  * NOISE   — unrelated services/tickets/commits/threads act as distractors.

So the AI's first answer (V1), working only from the sources, is incomplete or misled
(~60-75%). After the expert provides the correct, complete answer, the re-run (V2)
reflects it (~90-95%). That is a genuine learning gap, not a contrived one.

Run:  python data/build_dataset.py
"""
from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent
SOURCES_DIR = DATA_DIR / "sources"
WIKI_DIR = SOURCES_DIR / "wiki"


# --------------------------------------------------------------------------- #
# Structured entities (drive the knowledge graph)
# --------------------------------------------------------------------------- #
SERVICES = [
    {"name": "payments-service", "team": "team-payments", "owner": "Maya Chen", "depends_on": []},
    {"name": "checkout-service", "team": "team-checkout", "owner": "Raj Patel",
     "depends_on": ["payments-service", "auth-service"]},
    # STALE owner on purpose (real owner is Lena, established only in TICKET-160 / SLACK-04).
    {"name": "notifications-service", "team": "team-platform", "owner": "Sam Lee", "depends_on": []},
    {"name": "auth-service", "team": "team-platform", "owner": "Sam Lee", "depends_on": []},
    # --- NOISE / distractor services (unrelated to the gold questions) ---
    {"name": "search-service", "team": "team-search", "owner": "Priya Nair", "depends_on": []},
    {"name": "billing-service", "team": "team-billing", "owner": "Tom Reed",
     "depends_on": ["payments-service"]},
]

RELEASES = [
    {"id": "REL-v2.1", "name": "v2.1", "status": "released-late", "note": "Shipped 6 days behind schedule."},
    {"id": "REL-v2.2", "name": "v2.2", "status": "blocked", "note": "Not yet shipped."},
    {"id": "REL-v2.0", "name": "v2.0", "status": "released", "note": "Shipped on time, no issues."},  # NOISE
]

INCIDENTS = [
    {"id": "INC-9", "title": "Payment write failures spike", "service": "payments-service",
     "summary": "Elevated 500s on payment writes shortly after a deploy. Initial on-call notes "
                "speculated a traffic load spike."},
    {"id": "INC-12", "title": "Notification delivery delays", "service": "notifications-service",
     "summary": "Notifications delayed up to 30 minutes. First suspected to be database slowness."},
    {"id": "INC-15", "title": "Search latency regression", "service": "search-service",  # NOISE
     "summary": "Search p95 latency rose after a ranking change; rolled back, unrelated to payments."},
]

# Tickets: `blocks` -> release ids, `relates` -> incident ids.
TICKETS = [
    {"id": "TICKET-101", "title": "v2.1 release tracking", "status": "done",
     "service": "payments-service", "owner": "Maya Chen", "blocks": [], "relates": [],
     "body": "Umbrella ticket tracking the v2.1 release checklist and sign-offs."},
    {"id": "TICKET-123", "title": "Roll back DB migration 0042 on payments-service",
     "status": "done", "service": "payments-service", "owner": "Maya Chen",
     "blocks": ["REL-v2.1"], "relates": ["INC-9"],
     "body": ("Migration 0042 added a NOT NULL column `settled_at` without a default. Existing "
              "insert paths broke, causing payment write failures (INC-9). The v2.1 release was "
              "HELD until the migration was reverted and a backfill added.")},
    {"id": "TICKET-130", "title": "QA regression backlog cleanup", "status": "done",
     "service": "checkout-service", "owner": "Raj Patel", "blocks": [], "relates": [],
     "body": ("Routine QA regression backlog worked down before v2.1. Mentioned in the release "
              "notes but NOT on the release critical path.")},
    {"id": "TICKET-145", "title": "Auth token rotation dependency for v2.2",
     "status": "blocked", "service": "auth-service", "owner": "Sam Lee",
     "blocks": ["REL-v2.2"], "relates": [],
     "body": ("Checkout v2.2 depends on the new auth token-rotation endpoint. It is not yet "
              "delivered, so v2.2 is blocked until auth-service ships it.")},
    {"id": "TICKET-160", "title": "Ownership transfer: notifications-service",
     "status": "done", "service": "notifications-service", "owner": "Lena Ortiz",
     "blocks": [], "relates": [],
     "body": ("Ownership of notifications-service transferred from Sam Lee to Lena Ortiz. Sam now "
              "focuses on auth-service. (The service wiki page has not been updated.)")},
    # --- FALSE LEAD: a postmortem ticket that misattributes INC-9 ---
    {"id": "TICKET-180", "title": "INC-9 postmortem (draft)", "status": "done",
     "service": "payments-service", "owner": "Maya Chen", "blocks": [], "relates": ["INC-9"],
     "body": ("Draft postmortem. Early hypothesis: INC-9 was triggered by a traffic load spike "
              "during peak hours. (NOTE: this draft was later found to be incorrect.)")},
    # --- NOISE tickets ---
    {"id": "TICKET-170", "title": "Search relevance tuning", "status": "done",
     "service": "search-service", "owner": "Priya Nair", "blocks": [], "relates": ["INC-15"],
     "body": "Tune search ranking weights for the autumn catalogue. Unrelated to payments."},
    {"id": "TICKET-175", "title": "Invoice rounding bug", "status": "done",
     "service": "billing-service", "owner": "Tom Reed", "blocks": [], "relates": [],
     "body": "Fix half-cent rounding error on invoices. Unrelated to the release or incidents."},
]

# Commits: `service`, optional `release`.
COMMITS = [
    {"id": "COMMIT-a1b2", "service": "payments-service", "release": "REL-v2.1",
     "message": ("Revert migration 0042 (NOT NULL settled_at without default). It broke payment "
                 "writes and blocked the v2.1 release. Backfill planned before re-apply.")},
    {"id": "COMMIT-c3d4", "service": "checkout-service", "release": None,
     "message": ("checkout: switch retries to exponential backoff + jitter. Fixed-interval retries "
                 "amplified load and worsened the payments retry storm during INC-9.")},
    {"id": "COMMIT-e5f6", "service": "auth-service", "release": "REL-v2.2",
     "message": "auth: scaffold token-rotation endpoint (incomplete; not production-ready)."},
    {"id": "COMMIT-g7h8", "service": "notifications-service", "release": None,
     "message": ("notifications: lower worker concurrency from 16 to 2 by mistake in a config "
                 "refactor. This starved the delivery queue and caused INC-12. Reverting.")},
    # --- NOISE commits ---
    {"id": "COMMIT-i9j0", "service": "search-service", "release": None,
     "message": "search: adjust ranking weights for autumn catalogue (later rolled back, INC-15)."},
    {"id": "COMMIT-k1l2", "service": "billing-service", "release": None,
     "message": "billing: fix half-cent invoice rounding."},
]

# Slack threads: each is a self-contained discussion. `entities` lists referenced ids.
SLACK = [
    {"id": "SLACK-01", "channel": "#releases", "entities": ["REL-v2.1", "TICKET-123"],
     "text": ("Maya: v2.1 is held — migration 0042 broke payment writes, we're rolling it back. "
              "Raj: so it's not the QA backlog? Maya: correct, the QA backlog (TICKET-130) is "
              "separate and was never on the critical path.")},
    {"id": "SLACK-02", "channel": "#incidents", "entities": ["INC-9", "payments-service"],
     "text": ("Maya: payments 500s started right after the deploy. We first guessed a load spike, "
              "but traffic was normal — the real cause is migration 0042 adding a non-null column "
              "with no default. Reverting now (COMMIT-a1b2). We should add a payment-write alarm.")},
    {"id": "SLACK-03", "channel": "#checkout", "entities": ["checkout-service"],
     "text": ("Raj: the retry storm made INC-9 worse — fixed-interval retries hammered payments. "
              "Switching to exponential backoff with jitter and capping retries at 3.")},
    {"id": "SLACK-04", "channel": "#platform", "entities": ["notifications-service", "auth-service"],
     "text": ("Lena: I'm now the owner of notifications-service. Sam: yep, handed over; I'm on "
              "auth-service now. Please update the wiki, it's stale. Escalations go to the "
              "team-platform on-call.")},
    {"id": "SLACK-05", "channel": "#releases", "entities": ["REL-v2.2", "TICKET-145"],
     "text": ("Sam: v2.2 is blocked on the auth token-rotation endpoint (TICKET-145). It isn't done "
              "yet — realistically a couple of sprints out unless we pull in help.")},
    {"id": "SLACK-06", "channel": "#incidents", "entities": ["INC-12", "notifications-service"],
     "text": ("Lena: notification delays (INC-12) looked like DB slowness at first, but it was a "
              "config refactor dropping worker concurrency 16->2 (COMMIT-g7h8). We had no "
              "queue-depth alarm, which is why it took so long to spot.")},
    # --- NOISE threads ---
    {"id": "SLACK-07", "channel": "#search", "entities": ["search-service", "INC-15"],
     "text": "Priya: rolled back the ranking change, search latency back to normal. Unrelated to v2.x."},
    {"id": "SLACK-08", "channel": "#random", "entities": [],
     "text": "Tom: coffee machine on floor 3 is broken again. Anyone know who to ping?"},
]

# Wiki docs — several are deliberately MISLEADING or STALE.
WIKI = [
    {"id": "WIKI-release-v2.1", "title": "Release v2.1 notes", "service": "payments-service",
     "body": ("# Release v2.1\n\nv2.1 shipped about a week late. The delay is attributed to a "
              "**QA regression backlog**.\n\n_Official summary; see tickets and #releases for detail._")},
    # --- FALSE postmortem (prominent, will mislead a naive answer) ---
    {"id": "WIKI-inc9-postmortem", "title": "INC-9 postmortem", "service": "payments-service",
     "body": ("# INC-9 Postmortem\n\nSummary: payment write failures during peak hours.\n\n"
              "**Root cause:** a traffic load spike overwhelmed the payments database.\n\n"
              "_(This page reflects the initial hypothesis.)_")},
    {"id": "WIKI-payments-service", "title": "payments-service overview", "service": "payments-service",
     "body": "# payments-service\n\nHandles payment capture and settlement.\n\nOwner: team-payments (Maya Chen)."},
    {"id": "WIKI-notifications-service", "title": "notifications-service overview",
     "service": "notifications-service",
     "body": "# notifications-service\n\nSends transactional notifications.\n\nOwner: Sam Lee.  _(out of date)_"},
    {"id": "WIKI-checkout-service", "title": "checkout-service overview", "service": "checkout-service",
     "body": ("# checkout-service\n\nDrives the checkout funnel and calls payments-service for "
              "capture. Needs auth token-rotation for v2.2.\n\nOwner: team-checkout (Raj Patel).")},
    {"id": "WIKI-auth-service", "title": "auth-service overview", "service": "auth-service",
     "body": "# auth-service\n\nIssues and rotates auth tokens.\n\nOwner: team-platform (Sam Lee)."},
    {"id": "WIKI-search-service", "title": "search-service overview", "service": "search-service",  # NOISE
     "body": "# search-service\n\nProduct search and ranking.\n\nOwner: team-search (Priya Nair)."},
]


# --------------------------------------------------------------------------- #
# Gold scenarios — the EXPERT answer is more complete/correct than the sources.
# --------------------------------------------------------------------------- #
SCENARIOS = [
    {
        "id": "Q-01",
        "question": "What was the root cause of the INC-9 payment incident, and how was it fully resolved and prevented?",
        "question_type": "incident_rca",
        "topics": ["incident", "payments"],
        "gold_answer": ("The root cause was database migration 0042 on payments-service, which added a NOT NULL "
                        "column (settled_at) with no default and broke payment writes — NOT the traffic load spike "
                        "claimed in the postmortem wiki. It was resolved by reverting the migration (COMMIT-a1b2) and "
                        "running a backfill. To prevent recurrence the team added a mandatory pre-deploy migration "
                        "safety check and a payment-write failure alarm. The v2.1 release was held until this was done."),
        "gold_root_cause": "Migration 0042 added a non-null column without a default (not a load spike).",
        "gold_evidence_ids": ["TICKET-123", "COMMIT-a1b2", "SLACK-02"],
    },
    {
        "id": "Q-02",
        "question": "Why did checkout-service change its retry strategy, and what was the measured result?",
        "question_type": "design_decision",
        "topics": ["checkout", "payments", "reliability"],
        "gold_answer": ("checkout-service used fixed-interval retries, which during the INC-9 window amplified load and "
                        "worsened a retry storm against payments-service. The team switched to exponential backoff with "
                        "jitter and capped retries at 3 (COMMIT-c3d4). The measured result: retry-driven load on "
                        "payments dropped by roughly 80% and checkout error rates returned to baseline within a day."),
        "gold_root_cause": "Fixed-interval retries amplified load and worsened the payments retry storm.",
        "gold_evidence_ids": ["COMMIT-c3d4", "SLACK-03"],
    },
    {
        "id": "Q-03",
        "question": "If auth-service misses its deadline, what is the full downstream blast radius and how can it be mitigated?",
        "question_type": "impact_analysis",
        "topics": ["auth", "checkout", "release"],
        "gold_answer": ("auth-service owes the token-rotation endpoint (TICKET-145), which is undelivered. Directly, "
                        "checkout-service's v2.2 depends on it, so the v2.2 release is blocked. Indirectly, billing-"
                        "service's v2.2 reconciliation (which runs off checkout/payments) would also slip. Customer "
                        "impact: the new token-rotation security feature does not ship and the milestone date moves. "
                        "Mitigation: ship v2.2 with rotation behind a feature flag and fast-follow, or add a second "
                        "engineer to auth-service."),
        "gold_root_cause": "",
        "gold_evidence_ids": ["TICKET-145", "SLACK-05", "WIKI-checkout-service"],
    },
    {
        "id": "Q-04",
        "question": "The postmortem says v2.1 was delayed by a QA backlog and a load spike. Is that accurate?",
        "question_type": "release_delay",
        "topics": ["release", "payments"],
        "gold_answer": ("No — both are wrong. The QA regression backlog (TICKET-130) was real but off the critical "
                        "path, and there was no load spike; that was an incorrect early hypothesis in the postmortem. "
                        "The actual delay was caused by migration 0042 breaking payment writes (INC-9); v2.1 was held "
                        "until the migration was reverted (COMMIT-a1b2). Both the postmortem and the release-notes "
                        "wiki are misleading."),
        "gold_root_cause": "Migration 0042 added a non-null column without a default; QA backlog and load spike were not the cause.",
        "gold_evidence_ids": ["TICKET-123", "COMMIT-a1b2", "SLACK-01"],
    },
    {
        "id": "Q-05",
        "question": "Who currently owns notifications-service, and who is the escalation contact?",
        "question_type": "ownership",
        "topics": ["ownership", "notifications"],
        "gold_answer": ("Lena Ortiz (team-platform) currently owns notifications-service, transferred from Sam Lee "
                        "(TICKET-160). The wiki is stale and still lists Sam. Escalation goes to the team-platform "
                        "on-call rotation, with Sam Lee as a secondary contact given his prior ownership."),
        "gold_root_cause": "",
        "gold_evidence_ids": ["TICKET-160", "SLACK-04", "WIKI-notifications-service"],
    },
    {
        "id": "Q-06",
        "question": "What caused the INC-12 notification delays, and why did it take so long to detect?",
        "question_type": "incident_rca",
        "topics": ["incident", "notifications"],
        "gold_answer": ("The root cause was a config refactor that mistakenly dropped notifications-service worker "
                        "concurrency from 16 to 2 (COMMIT-g7h8), starving the delivery queue — it was initially "
                        "misdiagnosed as database slowness. Detection was slow because there was no queue-depth alarm; "
                        "the team added one as a follow-up. It was fixed by reverting the concurrency change."),
        "gold_root_cause": "A config refactor dropped worker concurrency from 16 to 2, starving the queue (not DB slowness).",
        "gold_evidence_ids": ["COMMIT-g7h8", "SLACK-06"],
    },
    {
        "id": "Q-07",
        "question": "What is blocking the v2.2 release, who must fix it, by when, and what is the mitigation?",
        "question_type": "milestone_blocker",
        "topics": ["release", "auth"],
        "gold_answer": ("v2.2 is blocked by the undelivered auth token-rotation endpoint (TICKET-145), which is only "
                        "scaffolded (COMMIT-e5f6). Sam Lee, the auth-service owner, must complete it; the current "
                        "estimate is about two sprints out. Mitigation: ship v2.2 with rotation behind a feature flag "
                        "and fast-follow, or pull in a second engineer to accelerate auth-service."),
        "gold_root_cause": "",
        "gold_evidence_ids": ["TICKET-145", "COMMIT-e5f6", "SLACK-05"],
    },
    {
        "id": "Q-08",
        "question": "Walk through the complete causal chain of the v2.1 delay, correcting any wrong theories.",
        "question_type": "release_delay",
        "topics": ["release", "payments", "incident"],
        "gold_answer": ("Migration 0042 added a NOT NULL column without a default, which broke payment writes (INC-9). "
                        "It was initially blamed on a traffic load spike and on a QA backlog — both wrong. Once the "
                        "real cause was identified, the migration was reverted (COMMIT-a1b2) and a backfill planned, "
                        "after which v2.1 shipped about six days late. The QA backlog was off the critical path and "
                        "there was no load spike."),
        "gold_root_cause": "Migration 0042 added a non-null column without a default, breaking payment writes.",
        "gold_evidence_ids": ["TICKET-123", "COMMIT-a1b2", "SLACK-01"],
    },
    {
        "id": "Q-09",
        "question": "If payments-service has a complete outage, what breaks, what is the customer impact, and how do we mitigate?",
        "question_type": "impact_analysis",
        "topics": ["payments", "checkout"],
        "gold_answer": ("checkout-service breaks first because it calls payments-service during the funnel, and "
                        "billing-service's reconciliation also fails since it depends on payments. Customer impact: "
                        "customers cannot complete checkout or payment. Mitigation: checkout already has exponential "
                        "backoff (COMMIT-c3d4); add a circuit breaker to fail fast with a 'try again later' message, "
                        "and queue billing reconciliation for replay once payments recovers."),
        "gold_root_cause": "",
        "gold_evidence_ids": ["WIKI-checkout-service", "COMMIT-c3d4"],
    },
    {
        "id": "Q-10",
        "question": "Across INC-9 and INC-12, what recurring process problem do they reveal, and how should it be fixed?",
        "question_type": "incident_rca",
        "topics": ["incident", "process"],
        "gold_answer": ("In both incidents the real root cause (a bad migration in INC-9; a bad concurrency config in "
                        "INC-12) was initially misdiagnosed (load spike; DB slowness) and was only found by reading the "
                        "deploy commits and #incidents Slack — the incident summaries and wikis were wrong. The "
                        "recurring problem is missing pre-deploy safety checks and missing alarms (a payment-write "
                        "alarm and a queue-depth alarm), plus postmortems written from assumptions. The fix is "
                        "mandatory deploy checks, those alarms, and evidence-based postmortems."),
        "gold_root_cause": "",
        "gold_evidence_ids": ["COMMIT-a1b2", "COMMIT-g7h8", "SLACK-06"],
    },
]


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def main() -> None:
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    WIKI_DIR.mkdir(parents=True, exist_ok=True)

    _write_json(SOURCES_DIR / "services.json", SERVICES)
    _write_json(SOURCES_DIR / "releases.json", RELEASES)
    _write_json(SOURCES_DIR / "incidents.json", INCIDENTS)
    _write_json(SOURCES_DIR / "tickets.json", TICKETS)
    _write_json(SOURCES_DIR / "commits.json", COMMITS)
    _write_json(SOURCES_DIR / "slack.json", SLACK)

    index = []
    for doc in WIKI:
        fname = f"{doc['id']}.md"
        (WIKI_DIR / fname).write_text(doc["body"], encoding="utf-8")
        index.append({"id": doc["id"], "title": doc["title"],
                      "service": doc["service"], "file": f"wiki/{fname}"})
    _write_json(SOURCES_DIR / "wiki_index.json", index)

    _write_json(DATA_DIR / "scenarios.json", SCENARIOS)

    print(f"Dataset written to {SOURCES_DIR}")
    print(f"  services={len(SERVICES)} releases={len(RELEASES)} incidents={len(INCIDENTS)} "
          f"tickets={len(TICKETS)} commits={len(COMMITS)} slack={len(SLACK)} wiki={len(WIKI)}")
    print(f"  scenarios={len(SCENARIOS)}")
    print("  includes FALSE leads (WIKI-inc9-postmortem, WIKI-release-v2.1, TICKET-180, stale "
          "WIKI-notifications) and NOISE (search/billing).")


if __name__ == "__main__":
    main()
