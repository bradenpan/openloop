"""Register existing skills as OpenLoop agents.

Scans agents/skills/ for directories containing SKILL.md, parses the
YAML frontmatter for name and description, and creates agent records
in the DB with skill_path set.

Usage:
    python -m scripts.register_skills
"""

import os
import re
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.openloop.database import SessionLocal
from backend.openloop.db.models import Agent

SKILLS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agents", "skills")


def parse_frontmatter(skill_md_path: str) -> dict:
    """Parse YAML frontmatter from a SKILL.md file."""
    with open(skill_md_path, encoding="utf-8") as f:
        content = f.read()

    result = {"name": None, "description": None}
    if not content.startswith("---"):
        return result

    end = content.find("---", 3)
    if end == -1:
        return result

    frontmatter = content[3:end]

    name_match = re.search(r"^name:\s*(.+)$", frontmatter, re.MULTILINE)
    if name_match:
        result["name"] = name_match.group(1).strip()

    # Handle both single-line and multi-line description
    desc_match = re.search(r"^description:\s*\|?\s*\n([\s\S]*?)(?=\n[a-zA-Z]|\Z)", frontmatter, re.MULTILINE)
    if desc_match:
        result["description"] = desc_match.group(1).strip()[:500]
    else:
        desc_match = re.search(r"^description:\s*(.+)$", frontmatter, re.MULTILINE)
        if desc_match:
            result["description"] = desc_match.group(1).strip()[:500]

    return result


def register_all_skills():
    """Scan agents/skills/ and register each as an OpenLoop agent."""
    if not os.path.isdir(SKILLS_DIR):
        print(f"Skills directory not found: {SKILLS_DIR}")
        return

    db = SessionLocal()
    registered = 0
    skipped = 0

    try:
        for entry in sorted(os.listdir(SKILLS_DIR)):
            skill_dir = os.path.join(SKILLS_DIR, entry)
            skill_md = os.path.join(skill_dir, "SKILL.md")

            if not os.path.isdir(skill_dir) or not os.path.exists(skill_md):
                continue

            fm = parse_frontmatter(skill_md)
            name = fm["name"] or entry
            description = fm["description"] or f"Agent based on {entry} skill"
            skill_path = f"agents/skills/{entry}"

            # Check if already registered
            existing = db.query(Agent).filter(Agent.name == name).first()
            if existing:
                if existing.skill_path == skill_path:
                    print(f"  SKIP  {name} (already registered)")
                    skipped += 1
                    continue
                # Update skill_path if it changed
                existing.skill_path = skill_path
                existing.description = description
                db.commit()
                print(f"  UPDATE {name} -> {skill_path}")
                registered += 1
                continue

            agent = Agent(
                name=name,
                description=description,
                skill_path=skill_path,
                default_model="sonnet",
            )
            db.add(agent)
            db.commit()
            print(f"  ADD    {name} -> {skill_path}")
            registered += 1

    finally:
        db.close()

    print(f"\nDone: {registered} registered, {skipped} skipped")


if __name__ == "__main__":
    print("Registering skills as OpenLoop agents...")
    register_all_skills()
