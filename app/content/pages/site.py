"""Site-wide content: footer, contact details, the shared directory and reviews blocks."""

from app.content.fields import Document, email, link, paragraph, section, text

SITE = Document(
    key="site",
    label="Site-wide content",
    group="Site-wide",
    description="The footer, opening hours, social links and the blocks repeated on many pages.",
    sections=(
        section(
            "brand",
            "Brand",
            text(
                "tagline",
                "Tagline",
                "Find trusted EV charger installers across the UK.",
                max_length=120,
                help="Shown under the logo in the footer and used in search snippets.",
            ),
            paragraph(
                "footer_text",
                "Footer description",
                "Compare up to 5 quotes from verified installers and get the right charger "
                "for your home or business.",
                max_length=240,
                rows=2,
            ),
            text("header_cta", "Header button", "Get Free Quotes", max_length=30),
        ),
        section(
            "contact",
            "Contact details",
            text("hours_days", "Opening days", "Monday – Friday", max_length=60),
            text("hours_time", "Opening hours", "9:00am – 5:00pm (UK time)", max_length=60),
            email(
                "privacy_email",
                "Privacy email",
                "privacy@pickasparky.co.uk",
                help="For data protection requests (Privacy Policy). The support email is set "
                "in Settings › Organisation.",
            ),
        ),
        section(
            "social",
            "Social links",
            link(
                "x_url",
                "X (Twitter) profile",
                "",
                help="Full https:// address. Leave blank to show the icon without a link.",
                required=False,
            ),
            link(
                "linkedin_url",
                "LinkedIn page",
                "",
                help="Full https:// address.",
                required=False,
            ),
            text(
                "follow_text",
                "Follow us text",
                "Get the latest EV news, tips and updates.",
                max_length=120,
            ),
        ),
        section(
            "directory",
            "Locations directory",
            text("eyebrow", "Eyebrow", "Explore more locations", max_length=60),
            text("title", "Title", "Find trusted installers in your area", max_length=100),
            text("nearby", "Column 1 title", "Locations Nearby", max_length=40),
            text("popular", "Column 2 title", "Popular Locations", max_length=40),
            text("more", "Column 3 title", "More Locations in the Area", max_length=40),
            text("other", "Column 4 title", "Other UK Locations", max_length=40),
            help='The "Find trusted installers in your area" block at the foot of most pages. '
            "Which towns appear is set in SEO & Locations.",
        ),
        section(
            "reviews",
            "Reviews block",
            text("title", "Title", "Real people. Real results.", max_length=80),
            paragraph(
                "lead",
                "Lead",
                "See what homeowners and businesses say about finding EV charger installers "
                "through PickASparky.",
                max_length=240,
                rows=2,
            ),
            help="The moving reviews on the home and location pages. Reviews themselves are "
            "moderated in Reviews.",
        ),
    ),
)
