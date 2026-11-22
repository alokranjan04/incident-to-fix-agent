"""Create one ServiceNow incident per seeded bug, and save the numbers for the evals.

Usage:
  python scripts/create_incidents.py --dry-run         # print what would be created
  python scripts/create_incidents.py                   # create incidents for bugs 02-15
  python scripts/create_incidents.py --ids 03 07       # only some bugs

Reads SNOW_INSTANCE_URL, SNOW_USER and SNOW_PASSWORD from the environment (see .env.example).
Bug 01 already exists as INC0010004, so it is skipped unless you pass --ids 01.
"""
import argparse
import json
import os

import requests

from _common import AGENT_ROOT, load_bugs, load_env

REPO = "incident-to-fix-demo"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    load_env()

    bugs = [b for b in load_bugs() if (b["id"] in args.ids if args.ids else b["id"] != "01")]
    out_path = AGENT_ROOT / "evals/incidents.json"
    numbers = json.loads(out_path.read_text()) if out_path.exists() else {"01": "INC0010004"}

    for bug in bugs:
        payload = {
            "short_description": bug["short_description"],
            "description": bug["description"].rstrip() + f"\n\nEnvironment: staging (branch {bug['branch']})",
            "category": "software_defect",
            "u_repo": REPO,
            "urgency": "2",
            "impact": "2",
        }
        if args.dry_run:
            print(json.dumps(payload, indent=2))
            continue
        r = requests.post(
            f"{os.environ['SNOW_INSTANCE_URL'].rstrip('/')}/api/now/table/incident",
            auth=(os.environ["SNOW_USER"], os.environ["SNOW_PASSWORD"]),
            headers={"Accept": "application/json"},
            json=payload,
            timeout=30,
        )
        r.raise_for_status()
        numbers[bug["id"]] = r.json()["result"]["number"]
        print(f"bug {bug['id']}: {numbers[bug['id']]}")

    if not args.dry_run:
        out_path.write_text(json.dumps(numbers, indent=2) + "\n")
        print(f"Saved incident numbers to {out_path}")


if __name__ == "__main__":
    main()
