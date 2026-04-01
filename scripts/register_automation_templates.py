"""Register pre-built automation templates into the database.

Creates an "Automation Agent" and three automation records:
  1. Daily Task Review     — every day at 8am, scans for overdue/stuck tasks
  2. Stale Work Check      — every Monday at 9am, finds items not updated in 7+ days
  3. Follow-up Reminder    — every day at 8am, finds CRM records with past-due follow-ups

Idempotent: checks by name before creating. Running twice is safe.

Usage:
    python -m scripts.register_automation_templates
    make register-automations
"""

import sys
from pathlib import Path

# Ensure project root is on path so imports resolve
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.openloop.database import SessionLocal
from backend.openloop.db.models import Agent, Automation
from backend.openloop.services import automation_service

# ---------------------------------------------------------------------------
# Automation Agent definition
# ---------------------------------------------------------------------------

AUTOMATION_AGENT_NAME = "Automation Agent"

AUTOMATION_AGENT_DESCRIPTION = (
    "Lightweight scanning agent that runs scheduled automations. "
    "Reads items across all spaces, identifies actionable findings, "
    "and records summaries to memory so they surface to the user."
)

AUTOMATION_AGENT_SYSTEM_PROMPT = """\
You are the Automation Agent for OpenLoop. You run scheduled background scans.

Your role is narrow and specific:
- Use the tools available to read item data across spaces
- Apply the criteria described in each run's instruction
- Record a clear, structured summary to memory using write_memory

You do NOT take action on items (no moving, editing, or deleting).
You do NOT ask clarifying questions — just run the scan and write the result.
You do NOT invent data. Report only what the tools return.

If a tool call fails, note it in your summary and continue with remaining items.
Always end by writing the result to memory, even if the result is "nothing found."

Be concise. Write summaries that a busy person can scan in 30 seconds.\
"""

# ---------------------------------------------------------------------------
# Template definitions
# ---------------------------------------------------------------------------

# NOTE ON TOOLS:
# list_items(space_id, item_type, is_done, limit) → {id, title, item_type, stage}
# get_item(item_id)                               → {id, title, item_type, stage,
#                                                    description, priority, space_id,
#                                                    created_by, created_at, updated_at}
# get_cross_space_tasks(is_done)                  → {id, title, is_done, space_id,
#                                                    stage, due_date}
# get_linked_items(item_id)                       → [{item_id, title, item_type,
#                                                    stage, is_done, link_type}]
# write_memory(namespace, key, value)             → stores the result

TEMPLATES = [
    {
        "name": "Daily Task Review",
        "description": (
            "Scans all spaces for overdue tasks and tasks that haven't moved stages. "
            "Produces a summary notification."
        ),
        "trigger_type": "cron",
        "cron_expression": "0 8 * * *",
        "enabled": False,
        "space_id": None,
        "instruction": """\
Run a daily task review across all spaces. Follow these steps precisely.

STEP 1 — GATHER ALL OPEN TASKS
Call get_cross_space_tasks with is_done="false". This returns all open tasks
across every space, including their due_date and space_id fields.

STEP 2 — IDENTIFY OVERDUE TASKS
From the list returned in step 1, identify tasks where due_date is not null
and the due_date is in the past (earlier than today's date). These are overdue.

STEP 3 — IDENTIFY STUCK TASKS
From the same list, for each task call get_item(item_id) to retrieve its
updated_at timestamp. A task is "stuck" if updated_at is more than 3 days ago.
Skip tasks that are already classified as overdue — only flag newly stuck items.

STEP 4 — GROUP BY SPACE
Group your findings by space_id. For display purposes, use the space_id as the
group identifier (space names are not directly available to you).

STEP 5 — COMPOSE THE SUMMARY
Write a plain-text summary in this format:

  === Daily Task Review — [TODAY'S DATE] ===

  OVERDUE TASKS ([count]):
  - [Space: space_id_here] "[task title]" — due [due_date]
  - ... (one per line)

  STUCK TASKS (not updated in 3+ days, [count]):
  - [Space: space_id_here] "[task title]" — last updated [updated_at date]
  - ... (one per line)

If there are no overdue or stuck tasks, write:
  === Daily Task Review — [TODAY'S DATE] ===
  All clear — no overdue or stuck tasks today.

STEP 6 — WRITE TO MEMORY
Call write_memory with:
  namespace = "global"
  key       = "daily_task_review_last_run"
  value     = [the full summary text from step 5]

This is your final output. Do not take any action on the items themselves.
""",
    },
    {
        "name": "Stale Work Check",
        "description": "Weekly scan for items not updated in 7+ days. Surfaces via notification.",
        "trigger_type": "cron",
        "cron_expression": "0 9 * * 1",
        "enabled": False,
        "space_id": None,
        "instruction": """\
Run a weekly stale work check across all spaces. Follow these steps precisely.

STEP 1 — GATHER ALL ACTIVE ITEMS
Call list_items with no filters (leave space_id, item_type, and is_done blank)
and limit="200". This returns all items across all spaces.
Then call list_items again with is_done="false" and limit="200" to get open items only.
Use the is_done=false results — you only care about items still in progress.

STEP 2 — RETRIEVE DETAILED TIMESTAMPS
For each item in the open list, call get_item(item_id) to get its updated_at field.
A stale item is one where updated_at is more than 7 days ago.

STEP 3 — FILTER STALE ITEMS
Collect all items where updated_at < (today - 7 days). Skip items where is_done=true
(they are finished work). Skip items with item_type="record" if they have no stage
(they may be passive reference records rather than active work).

STEP 4 — GROUP BY SPACE
Group stale items by space_id. Use space_id as the group label.

STEP 5 — COMPOSE THE SUMMARY
Write a plain-text summary in this format:

  === Stale Work Check — Week of [TODAY'S DATE] ===

  STALE ITEMS (not updated in 7+ days, [count] total):

  [Space: space_id_here] ([count] items):
  - "[item title]" — [item_type], stage: [stage], last updated: [updated_at date]
  - ...

  [Space: space_id_here] ([count] items):
  - ...

If no stale items are found, write:
  === Stale Work Check — Week of [TODAY'S DATE] ===
  No stale items found. All active work has been touched in the last 7 days.

STEP 6 — WRITE TO MEMORY
Call write_memory with:
  namespace = "global"
  key       = "stale_work_check_last_run"
  value     = [the full summary text from step 5]

This is your final output. Do not update, move, or modify any items.
""",
    },
    {
        "name": "Follow-up Reminder",
        "description": (
            "Scans CRM records with a next_follow_up field that is past due, "
            "plus linked tasks. Surfaces via notification."
        ),
        "trigger_type": "cron",
        "cron_expression": "0 8 * * *",
        "enabled": False,
        "space_id": None,
        "instruction": """\
Run a daily follow-up reminder scan across all CRM records. Follow these steps precisely.

BACKGROUND:
CRM records are items with item_type="record". They may have a custom_fields object
containing a "next_follow_up" key whose value is an ISO date string (e.g. "2025-04-01").
You cannot filter by custom_fields directly — you must retrieve each record and inspect it.

STEP 1 — GATHER ALL RECORDS
Call list_items with item_type="record" and is_done="false" and limit="200".
This returns all open records across all spaces.

STEP 2 — RETRIEVE FULL DETAILS
For each record returned in step 1, call get_item(item_id).
The get_item response does not include custom_fields directly. However, the item's
description field may contain follow-up information written by the user or a previous agent.

Note: If get_item does not expose custom_fields, use the description field as your
signal. Look for dates mentioned in the description that appear to be follow-up deadlines
(phrases like "follow up by", "next follow-up", "check in on", or explicit date strings).
A record is overdue if the follow-up date mentioned in the description is in the past.

STEP 3 — CHECK FOR LINKED TASKS
For each record that has an overdue follow-up, call get_linked_items(item_id).
From the results, collect any linked items where is_done=false — these are open tasks
still associated with this contact or record.

STEP 4 — COMPOSE THE SUMMARY
Write a plain-text summary in this format:

  === Follow-up Reminder — [TODAY'S DATE] ===

  OVERDUE FOLLOW-UPS ([count]):

  "[Record title]" (space: [space_id]):
    Follow-up date: [date extracted from description or custom field]
    Open linked tasks ([count]):
    - "[task title]" — stage: [stage]
    - ...
    (No linked tasks) — if none

  "[Record title]" ...

If nothing is due, write:
  === Follow-up Reminder — [TODAY'S DATE] ===
  No follow-ups due today.

STEP 5 — WRITE TO MEMORY
Call write_memory with:
  namespace = "global"
  key       = "follow_up_reminder_last_run"
  value     = [the full summary text from step 4]

This is your final output. Do not modify any records or tasks.
""",
    },
]

# ---------------------------------------------------------------------------
# Main registration logic
# ---------------------------------------------------------------------------


def get_or_create_automation_agent(db) -> Agent:
    """Find the Automation Agent by name, or create it if it doesn't exist."""
    existing = db.query(Agent).filter(Agent.name == AUTOMATION_AGENT_NAME).first()
    if existing:
        print(f"  SKIP  Agent '{AUTOMATION_AGENT_NAME}' (already exists, id={existing.id})")
        return existing

    agent = Agent(
        name=AUTOMATION_AGENT_NAME,
        description=AUTOMATION_AGENT_DESCRIPTION,
        system_prompt=AUTOMATION_AGENT_SYSTEM_PROMPT,
        default_model="sonnet",
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    print(f"  ADD   Agent '{AUTOMATION_AGENT_NAME}' (id={agent.id})")
    return agent


def register_templates(db, agent_id: str) -> None:
    """Create each automation template if it does not already exist (checked by name)."""
    created = 0
    skipped = 0

    for tmpl in TEMPLATES:
        existing = db.query(Automation).filter(Automation.name == tmpl["name"]).first()
        if existing:
            print(f"  SKIP  Automation '{tmpl['name']}' (already exists, id={existing.id})")
            skipped += 1
            continue

        automation_service.create_automation(
            db,
            name=tmpl["name"],
            description=tmpl["description"],
            agent_id=agent_id,
            instruction=tmpl["instruction"],
            trigger_type=tmpl["trigger_type"],
            cron_expression=tmpl["cron_expression"],
            space_id=tmpl["space_id"],
            enabled=tmpl["enabled"],
        )
        cron = tmpl["cron_expression"]
        print(f"  ADD   Automation '{tmpl['name']}' (cron={cron}, enabled=False)")
        created += 1

    print(f"\n  Automations: {created} created, {skipped} skipped")


def main() -> None:
    print("Registering automation templates...")
    db = SessionLocal()
    try:
        agent = get_or_create_automation_agent(db)
        register_templates(db, agent.id)
        print("\nDone.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
