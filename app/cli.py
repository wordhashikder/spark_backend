"""Operational commands: `python -m app.cli <command>`."""

import argparse
import asyncio
import getpass
import sys
from email.message import EmailMessage
from pathlib import Path

import aiosmtplib
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import SessionFactory, engine
from app.core.exceptions import AppError
from app.models import Location
from app.schemas.common import Email, Password
from app.services import locations, media, seeding
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

    move = commands.add_parser(
        "migrate-media",
        help="upload the images bundled with the website (town photos, blog covers, showcase"
        " logos and galleries) to Cloudinary and point the database at them",
    )
    move.add_argument(
        "--source",
        type=Path,
        help="the website's public/ folder (default: ../frontend/public next to the backend,"
        " otherwise downloaded from FRONTEND_URL)",
    )
    move.add_argument("--dry-run", action="store_true", help="show what would be uploaded")

    probe = commands.add_parser(
        "test-email",
        help="send one test email with the SMTP_* settings and print the exact error, if any",
    )
    probe.add_argument("to", help="address to send the test to")

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


_DEFAULT_PUBLIC_DIR = Path(__file__).resolve().parents[2] / "frontend" / "public"


def _media_source(folder: Path | None) -> media.MediaSource:
    if folder is not None:
        if not folder.is_dir():
            raise seeding.SeedingError(f"No such folder: {folder}")
        return media.DirectorySource(folder)
    if _DEFAULT_PUBLIC_DIR.is_dir():
        return media.DirectorySource(_DEFAULT_PUBLIC_DIR)
    return media.HttpSource(get_settings().frontend_url)


async def _migrate_media(
    session: AsyncSession, *, folder: Path | None = None, dry_run: bool = False
) -> str:
    settings = get_settings()
    if not settings.cloudinary_configured:
        raise seeding.SeedingError("Set the CLOUDINARY_* variables to upload images.")
    report = await media.migrate_bundled_media(
        session, build_storage(settings), _media_source(folder), dry_run=dry_run
    )
    return ("(dry run) " if dry_run else "") + report.summary()


async def _seed_then_move_media(session: AsyncSession, result: str) -> str:
    """After seeding, put the bundled images in Cloudinary too (when it is configured).

    A problem here never fails the seeding: the command can be run again at any time.
    """
    if not get_settings().cloudinary_configured:
        return f"{result}\nCloudinary is not configured: images still point at the website."
    try:
        return f"{result}\nImages: {await _migrate_media(session)}"
    except Exception as exc:
        return f"{result}\nImages not moved to Cloudinary yet ({exc}); run migrate-media."


async def _test_email(to: str) -> str:
    """Send a plain message and report the real outcome (normal sending only logs failures)."""
    settings = get_settings()
    if not settings.smtp_configured:
        raise seeding.SeedingError("SMTP_HOST is empty, so nothing would be sent.")
    shown = (
        f"host={settings.smtp_host} port={settings.smtp_port} user={settings.smtp_username} "
        f"use_tls={settings.smtp_use_tls} start_tls={settings.smtp_start_tls} "
        f"from={settings.email_from}"
    )
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = to
    message["Subject"] = "PickASparky SMTP test"
    message.set_content("If you can read this, the SMTP settings work.")
    try:
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
            start_tls=settings.smtp_start_tls,
            timeout=20,
        )
    except Exception as exc:
        raise seeding.SeedingError(f"{type(exc).__name__}: {exc}\nSettings used: {shown}") from exc
    return f"Sent to {to}.\nSettings used: {shown}"


async def _run(args: argparse.Namespace) -> str:
    if args.command == "test-email":
        return await _test_email(args.to)
    try:
        async with SessionFactory() as session:
            match args.command:
                case "seed-locations":
                    done = f"Upserted {await seeding.seed_locations(session)} locations."
                    return await _seed_then_move_media(session, done)
                case "seed-content":
                    applied = await seeding.seed_content(session)
                    done = (
                        "\n".join(f"Added {name}: {count} rows." for name, count in applied)
                        if applied
                        else "Content is up to date."
                    )
                    return await _seed_then_move_media(session, done)
                case "migrate-media":
                    return await _migrate_media(session, folder=args.source, dry_run=args.dry_run)
                case "create-admin":
                    email, password = _admin_credentials(args)
                    admin = await seeding.create_admin(session, email, password)
                    return f"Created admin {admin.email}."
                case "seed-demo" if args.purge:
                    return f"Removed {await seeding.purge_demo(session)} demo accounts."
                case "seed-demo":
                    done = f"Seeded {await seeding.seed_demo(session)} demo installers."
                    return await _seed_then_move_media(session, done)
                case "seed-blog" if args.purge:
                    return f"Removed {await seeding.purge_blog(session)} sample blog posts."
                case "seed-blog":
                    added = await seeding.seed_blog(session, only_if_empty=args.if_empty)
                    return await _seed_then_move_media(
                        session, f"Published {added} sample blog posts."
                    )
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
