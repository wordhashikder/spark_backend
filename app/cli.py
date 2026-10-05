"""Operational commands: `python -m app.cli <command>`."""

import argparse
import asyncio
import getpass
import sys

from pydantic import TypeAdapter, ValidationError

from app.core.database import SessionFactory, engine
from app.schemas.common import Email, Password
from app.services import seeding


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("seed-locations", help="upsert the locations from app/data/locations.json")

    admin = commands.add_parser("create-admin", help="create a verified admin account")
    admin.add_argument("--email", help="admin email address (prompted for when omitted)")
    admin.add_argument("--password", help="admin password (prompted for when omitted)")

    demo = commands.add_parser("seed-demo", help="load demo data (never in production)")
    demo.add_argument("--purge", action="store_true", help="remove the demo data instead")
    return parser


def _admin_credentials(args: argparse.Namespace) -> tuple[str, str]:
    email = args.email or input("Admin email: ")
    password = args.password or getpass.getpass("Admin password: ")
    try:
        return (
            TypeAdapter(Email).validate_python(email),
            TypeAdapter(Password).validate_python(password),
        )
    except ValidationError as exc:
        reasons = "; ".join(error["msg"] for error in exc.errors())
        raise seeding.SeedingError(reasons) from exc


async def _run(args: argparse.Namespace) -> str:
    try:
        async with SessionFactory() as session:
            match args.command:
                case "seed-locations":
                    return f"Upserted {await seeding.seed_locations(session)} locations."
                case "create-admin":
                    email, password = _admin_credentials(args)
                    admin = await seeding.create_admin(session, email, password)
                    return f"Created admin {admin.email}."
                case "seed-demo" if args.purge:
                    return f"Removed {await seeding.purge_demo(session)} demo accounts."
                case "seed-demo":
                    return f"Seeded {await seeding.seed_demo(session)} demo installers."
        raise seeding.SeedingError(f"Unknown command: {args.command}")
    finally:
        await engine.dispose()


def main() -> int:
    args = _build_parser().parse_args()
    try:
        print(asyncio.run(_run(args)))
    except seeding.SeedingError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
