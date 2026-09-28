"""Local administrator commands. Never accept a password on the command line."""

import argparse
import sys
from getpass import getpass

from .db import PostgresStore


def main() -> None:
    parser = argparse.ArgumentParser(description="ETL-Agent local account bootstrap")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("init-db")
    account = actions.add_parser("account")
    account.add_argument("username")
    project = actions.add_parser("project")
    project.add_argument("project_id")
    project.add_argument("name")
    member = actions.add_parser("member")
    member.add_argument("username")
    member.add_argument("project_id")
    member.add_argument("role", choices=["Maker", "DataApprover", "SecurityApprover", "Operator", "Auditor"])
    args = parser.parse_args()
    store = PostgresStore()
    try:
        if args.action == "init-db":
            store.init_schema()
        elif args.action == "account":
            if not sys.stdin.isatty():
                parser.error("Interactive terminal required for password input")
            password = getpass("Password: ")
            if password != getpass("Repeat password: "):
                parser.error("Passwords do not match")
            store.add_account(args.username, password)
        elif args.action == "project":
            store.add_project(args.project_id, args.name)
        else:
            store.add_member(args.username, args.project_id, args.role)
    except ValueError as exc:
        parser.error(str(exc))
    except Exception:
        raise SystemExit("Bootstrap failed; check database access and existing records without printing credentials") from None
    print("Done")


if __name__ == "__main__":
    main()
