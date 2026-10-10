"""Operational commands: `python -m app.cli <command>`."""

import argparse
import asyncio
import getpass
import sys
from pathlib import Path

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import SessionFactory, engine
from app.core.exceptions import AppError
from app.models import Location
from app.schemas.common import Email, Password
from app.services import locations, seeding
from app.services.storage import build_storage


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("seed-locations", help="upsert the locations from app/data/locations.json")
    commands.add_parser(
        "seed-content",
        help="add the content batches not added yet: blog articles, directory listings"
        " and (outside production, or with SEED_SHOWCASE=true) the showcase installers",
    )

    admin = commands.add_parser("create-admin", help="create a verified admin account")
    admin.add_argument("--email", help="admin email address (prompted for when omitted)")
    admin.add_argument("--password", help="admin password (prompted for when omitted)")

    demo = commands.add_parser("seed-demo", help="load demo data (never in production)")
    demo.add_argument("--purge", action="store_true", help="remove the demo data instead")

    blog = commands.add_parser(
        "seed-blog", help="publish the sample blog posts from app/data/blog.json"
    )
    blog_mode = blog.add_mutually_exclusive_group()
    blog_mode.add_argument("--purge", action="store_true", help="remove the sample posts instead")
    blog_mode.add_argument(
        "--if-empty",
        action="store_true",
        help="only when the blog has no posts at all",
    )

    image = commands.add_parser(
        "location-image", help="upload a photo for a location page (needs Cloudinary)"
    )
    image.add_argument("slug", help="location slug, e.g. cardiff")
    image.add_argument("file", type=Path, help="JPEG, PNG or WebP file, at most 5 MB")
    image.add_argument("--alt", help="alt text (default: '<town>, <region>')")
    image.add_argument("--credit", help="photo credit shown on the page, e.g. 'Photo: Jane Doe'")
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


async def _upload_location_image(session: AsyncSession, args: argparse.Namespace) -> Location:
    settings = get_settings()
    if not settings.cloudinary_configured:
        raise seeding.SeedingError("Set the CLOUDINARY_* variables to upload images.")
    if not args.file.is_file():
        raise seeding.SeedingError(f"No such file: {args.file}")
    try:
        return await locations.set_image(
            session,
            args.slug,
            args.file.read_bytes(),
            build_storage(settings),
            alt=args.alt,
            credit=args.credit,
        )
    except AppError as exc:
        raise seeding.SeedingError(exc.message) from exc


async def _run(args: argparse.Namespace) -> str:
    try:
        async with SessionFactory() as session:
            match args.command:
                case "seed-locations":
                    return f"Upserted {await seeding.seed_locations(session)} locations."
                case "seed-content":
                    applied = await seeding.seed_content(session)
                    if not applied:
                        return "Content is up to date."
                    return "\n".join(f"Added {name}: {count} rows." for name, count in applied)
                case "create-admin":
                    email, password = _admin_credentials(args)
                    admin = await seeding.create_admin(session, email, password)
                    return f"Created admin {admin.email}."
                case "seed-demo" if args.purge:
                    return f"Removed {await seeding.purge_demo(session)} demo accounts."
                case "seed-demo":
                    return f"Seeded {await seeding.seed_demo(session)} demo installers."
                case "seed-blog" if args.purge:
                    return f"Removed {await seeding.purge_blog(session)} sample blog posts."
                case "seed-blog":
                    added = await seeding.seed_blog(session, only_if_empty=args.if_empty)
                    return f"Published {added} sample blog posts."
                case "location-image":
                    location = await _upload_location_image(session, args)
                    return f"Set the photo for {location.name}: {location.image_url}"
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
