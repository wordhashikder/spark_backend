"""The back office's modules and which staff roles may use them (the role matrix).

Every admin API route belongs to a module, worked out from its path, and the admin router
checks the signed-in team member's role against the matrix before the route runs (see
`require_admin_access` in `app/api/deps.py`). An admin path that no module claims is
open to owners only, so a new route is closed until it is mapped here.

Owners can use everything and are not editable. For the other roles, the matrix starts
from `DEFAULT_ACCESS` and owners change it in the Dashboard (Role Matrix), which stores
only the cells that differ from these defaults.
"""

from dataclasses import dataclass

from app.core.enums import StaffRole


@dataclass(frozen=True, slots=True)
class Module:
    key: str
    label: str
    description: str
    # Admin API paths (after `/admin/`) that belong to the module.
    paths: tuple[str, ...]


MODULES: tuple[Module, ...] = (
    Module("overview", "Overview", "Headline numbers and recent activity.", ("overview",)),
    Module(
        "leads",
        "Leads & Quotes",
        "Quote requests, customers, who they went to, profile enquiries; sending held requests.",
        ("quotes", "enquiries", "customers"),
    ),
    Module(
        "messages",
        "Messages",
        "Every conversation between installers and homeowners; replying as the team.",
        ("conversations",),
    ),
    Module(
        "installers",
        "Installers",
        "Approve, edit plans, add and import listings, claim invitations.",
        ("installers",),
    ),
    Module(
        "locations",
        "SEO & Locations",
        "Location pages: content, search snippets, photos, drafts.",
        ("locations",),
    ),
    Module(
        "content",
        "Site content",
        "Every section, title and description of the public pages.",
        ("content",),
    ),
    Module("blog", "Blog", "Write, schedule and publish articles.", ("blog",)),
    Module("reviews", "Reviews", "Publish or reject homeowner reviews.", ("reviews",)),
    Module("inbox", "Contact inbox", "Messages from the contact form.", ("contact-messages",)),
    Module(
        "settings",
        "Settings",
        "Matching rules, notifications and organisation details.",
        ("settings", "platform"),
    ),
    Module(
        "billing",
        "Plans & billing",
        "Membership plans and prices, subscriptions, payments and Stripe sync (owners by default).",
        ("plans", "payments"),
    ),
    Module(
        "team",
        "Team & roles",
        "Invite team members, change their roles, edit this matrix (owners only).",
        ("team", "roles"),
    ),
)
MODULE_KEYS: tuple[str, ...] = tuple(module.key for module in MODULES)

DEFAULT_ACCESS: dict[StaffRole, frozenset[str]] = {
    StaffRole.OWNER: frozenset(MODULE_KEYS),
    StaffRole.MANAGER: frozenset(
        {
            "overview",
            "leads",
            "messages",
            "installers",
            "locations",
            "content",
            "blog",
            "reviews",
            "inbox",
        }
    ),
    StaffRole.EDITOR: frozenset({"overview", "locations", "content", "blog", "reviews"}),
    StaffRole.SUPPORT: frozenset({"overview", "leads", "messages", "installers", "inbox"}),
}

ROLE_LABELS: dict[StaffRole, tuple[str, str]] = {
    StaffRole.OWNER: ("Owner", "Full access, including the team and this matrix."),
    StaffRole.MANAGER: ("Manager", "Runs the marketplace day to day."),
    StaffRole.EDITOR: ("Editor", "Looks after the website's content and SEO."),
    StaffRole.SUPPORT: ("Support", "Helps homeowners and installers."),
}

# Uploads serve several editors; any one of these modules allows them.
_SHARED_PATHS: dict[str, frozenset[str]] = {
    "media": frozenset({"content", "blog", "locations"}),
    # Every team member may search and see the sidebar counts; results are filtered to
    # the modules their role allows.
    "search": frozenset(MODULE_KEYS),
    "nav": frozenset(MODULE_KEYS),
}


def modules_for_path(admin_path: str) -> frozenset[str] | None:
    """The modules that grant access to an admin API path (relative to `/admin/`).

    `None` means no module claims the path: owners only.
    """
    first = admin_path.strip("/").split("/", 1)[0]
    if first in _SHARED_PATHS:
        return _SHARED_PATHS[first]
    for module in MODULES:
        if first in module.paths:
            return frozenset({module.key})
    return None
