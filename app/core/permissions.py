"""The role matrix: who can do what in the Dashboard and the API.

Enforced by the route dependencies (`AdminDep`, `InstallerDep` in `app/api/deps.py`) and
the plan capabilities (`app/core/plans.py`); this table documents those rules for the
Role Matrix page, so keep it in step when access rules change.
"""

from app.core.enums import Role
from app.schemas.admin import Permission, RoleInfo, RoleMatrix

_A = [Role.ADMIN]
_I = [Role.INSTALLER]
_AI = [Role.ADMIN, Role.INSTALLER]

ROLE_MATRIX = RoleMatrix(
    roles=[
        RoleInfo(
            role=Role.ADMIN,
            label="Admin",
            description="PickASparky staff. Runs the marketplace: installers, leads, "
            "content, reviews and settings.",
        ),
        RoleInfo(
            role=Role.INSTALLER,
            label="Installer",
            description="A business with a listing. Manages its own profile; on the Pro and "
            "Premium plans it also receives leads, messages customers and sends quotes.",
        ),
    ],
    permissions=[
        Permission(
            key="dashboard.sign_in", area="Account", label="Sign in to the Dashboard", roles=_AI
        ),
        Permission(key="account.password", area="Account", label="Change own password", roles=_AI),
        Permission(
            key="profile.edit",
            area="Profile",
            label="Edit own business profile, services and areas",
            roles=_I,
        ),
        Permission(
            key="profile.media",
            area="Profile",
            label="Upload logo and gallery photos (plan limits apply)",
            roles=_I,
        ),
        Permission(
            key="leads.receive",
            area="Leads",
            label="Receive matched leads (Pro and Premium)",
            roles=_I,
        ),
        Permission(
            key="leads.contact",
            area="Leads",
            label="See customer contact details (Pro and Premium)",
            roles=_I,
        ),
        Permission(
            key="quotes.send",
            area="Quotes & messages",
            label="Message customers and send quotes (Pro and Premium)",
            roles=_I,
        ),
        Permission(
            key="quotes.view_all",
            area="Quotes & messages",
            label="Read every conversation and quote",
            roles=_A,
        ),
        Permission(
            key="leads.view_all",
            area="Leads",
            label="See every quote request, lead and enquiry",
            roles=_A,
        ),
        Permission(
            key="installers.moderate",
            area="Installers",
            label="Approve, reject, suspend, feature and change plans",
            roles=_A,
        ),
        Permission(
            key="installers.claim_invite",
            area="Installers",
            label="Send claim invitations to free listings",
            roles=_A,
        ),
        Permission(
            key="accreditations.verify", area="Installers", label="Verify accreditations", roles=_A
        ),
        Permission(
            key="reviews.moderate", area="Content", label="Publish or reject reviews", roles=_A
        ),
        Permission(
            key="blog.manage",
            area="Content",
            label="Write, publish and delete blog articles",
            roles=_A,
        ),
        Permission(
            key="locations.manage",
            area="SEO & locations",
            label="Edit location intros, photos and search snippets",
            roles=_A,
        ),
        Permission(key="contact.read", area="Inbox", label="Read contact-form messages", roles=_A),
        Permission(
            key="platform.view", area="Settings", label="View platform configuration", roles=_A
        ),
    ],
)
