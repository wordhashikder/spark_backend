"""Templates and journeys: blog listing, the quote form page and every location page."""

from app.content.fields import (
    Document,
    fixed_cards,
    paragraph,
    section,
    seo,
    text,
)

BLOG = Document(
    key="blog",
    label="Blog listing",
    group="Pages",
    path="/blog/",
    description="The blog's listing page. Articles themselves are edited in Blog.",
    sections=(
        seo(
            "EV Charging Guides and Advice",
            "Practical guides to choosing, installing and running a home EV charger in the UK: "
            "costs, chargers, installation, regulations and choosing an installer.",
        ),
        section(
            "hero",
            "Hero",
            text("eyebrow", "Eyebrow", "PickASparky Blog", max_length=40),
            text("title", "Heading (H1)", "EV Charging Guides and Advice", max_length=100),
            paragraph(
                "lead",
                "Introduction",
                "Clear, practical advice from the PickASparky team on choosing, installing and "
                "running a home EV charger.",
                max_length=300,
            ),
        ),
        section(
            "empty",
            "When there are no articles",
            text("title", "Title", "New articles are on their way", max_length=80),
            paragraph(
                "text",
                "Text",
                "In the meantime, compare free quotes from vetted EV charger installers in your "
                "area.",
                max_length=240,
                rows=2,
            ),
        ),
        section(
            "cta",
            "Call to action",
            text("eyebrow", "Eyebrow", "Ready when you are", max_length=60),
            text(
                "title",
                "Title",
                "Compare up to 5 free quotes from trusted EV charger installers",
                max_length=100,
            ),
            paragraph(
                "lead",
                "Text",
                "Answer six quick questions and get quotes from vetted installers who cover your "
                "postcode.",
                max_length=240,
                rows=2,
            ),
            text("button", "Button", "Get Free Quotes", max_length=30),
        ),
    ),
)

GET_QUOTES = Document(
    key="get-quotes",
    label="Get quotes (quote form)",
    group="Pages",
    path="/get-quotes/",
    description="The heading and steps around the quote questionnaire.",
    sections=(
        seo(
            "Get Free EV Charger Installation Quotes",
            "Get up to 5 free EV charger installation quotes from vetted local installers. Enter "
            "your postcode, answer 6 short questions and compare. No obligation.",
        ),
        section(
            "intro",
            "Heading",
            text("eyebrow", "Eyebrow", "Free EV charger quotes", max_length=40),
            text(
                "title",
                "Heading (H1)",
                "Get free EV charger installation quotes",
                max_length=100,
            ),
            paragraph(
                "lead",
                "Introduction",
                "Answer 6 short questions and we'll match you with up to 5 vetted, local "
                "installers. It's free and there's no obligation.",
                max_length=300,
            ),
            help="The questions themselves are part of the matching logic and change with the "
            "developers.",
        ),
        section(
            "steps",
            "How getting quotes works",
            text("title", "Title", "How getting quotes works", max_length=80),
            fixed_cards(
                "items",
                "Steps",
                "step",
                [
                    {
                        "title": "Answer 6 short questions",
                        "text": "Tell us about the charger, your property and your timing. Most "
                        "answers are a single tap.",
                    },
                    {
                        "title": "Get matched locally",
                        "text": "We match your request with up to 5 vetted installers whose "
                        "service area covers your postcode.",
                    },
                    {
                        "title": "Compare and choose",
                        "text": "Matched installers get in touch with their quotes. It's free, and "
                        "you choose who to contact.",
                    },
                ],
                help="Numbered automatically.",
            ),
        ),
    ),
)

LOCATION = Document(
    key="location",
    label="Location pages (all towns)",
    group="Templates",
    path="/uk/ev-charger-installers/manchester/",
    description="The wording every town and city page shares. Type {city} where the town's "
    "name goes. Each town's own SEO title, heading and introduction are edited in "
    "SEO & Locations and replace these.",
    sections=(
        seo(
            "EV Charger Installers in {city}",
            "Compare up to 5 free quotes from vetted EV charger installers in {city}. Enter "
            "your postcode, see trusted local electricians and choose who to contact.",
        ),
        section(
            "hero",
            "Hero",
            text("line1", "Heading, line 1", "Find trusted", max_length=60),
            text("line2", "Heading, line 2", "EV charger installers in {city}", max_length=80),
            text("highlight", "Heading, green line", "Compare up to 5 quotes", max_length=60),
            paragraph(
                "lead",
                "Introduction",
                "Enter your postcode and we'll connect you with trusted, local EV charger "
                "installers. It's free and there's no obligation.",
                max_length=300,
            ),
            help='A town\'s own "H1 heading" (SEO & Locations) replaces lines 1 and 2.',
        ),
        section(
            "installers",
            "Installer list",
            text("eyebrow", "Eyebrow", "Trusted local installers", max_length=60),
            text("title", "Title", "EV charger installers in {city}", max_length=100),
            paragraph(
                "lead",
                "Text",
                "Here are some of the trusted EV charger installers covering {city} and "
                "surrounding areas.",
                max_length=240,
                rows=2,
            ),
            text("search_link", "Link text", "Search Installers", max_length=30),
        ),
        section(
            "steps",
            "3 simple steps",
            text("eyebrow", "Eyebrow", "How it works", max_length=40),
            text(
                "title",
                "Title",
                "Get your EV charger installed in 3 simple steps",
                max_length=100,
            ),
            paragraph(
                "lead",
                "Lead",
                "We make it easy to find and compare trusted local installers in {city}.",
                max_length=240,
                rows=2,
            ),
            fixed_cards(
                "items",
                "Steps",
                "step",
                [
                    {
                        "title": "Request a free quote",
                        "text": "Enter your postcode and tell us what you need. It only takes a "
                        "minute and there's no obligation.",
                    },
                    {
                        "title": "Receive quotes from vetted installers",
                        "text": "We'll match you with up to 5 trusted, local EV charger "
                        "installers in {city}.",
                    },
                    {
                        "title": "Choose the right installer",
                        "text": "Compare your quotes and each installer's reviews, then choose "
                        "who to contact. The decision is always yours.",
                    },
                ],
            ),
        ),
        section(
            "why",
            "Why choose PickASparky",
            text("title", "Title", "Why choose PickASparky in {city}?", max_length=100),
            fixed_cards(
                "cards",
                "Cards",
                "card",
                [
                    {
                        "title": "Verified installers",
                        "text": "Local, qualified and reviewed electricians.",
                    },
                    {
                        "title": "Up to 5 quotes",
                        "text": "Compare quotes from trusted local installers.",
                    },
                    {
                        "title": "Local expertise",
                        "text": "Installers who know {city} and the surrounding areas.",
                    },
                    {
                        "title": "You're in control",
                        "text": "It's free, with no obligation, and you choose who to contact.",
                    },
                ],
            ),
        ),
        section(
            "local",
            "Local block",
            text("pill", "Photo badge", "Powering a greener {city}", max_length=60),
            text("eyebrow", "Eyebrow", "EV charging in {city}", max_length=60),
            text("title", "Title", "EV charger installation in {city}", max_length=100),
            paragraph(
                "intro",
                "Introduction (when a town has none)",
                "Whether you need a home charger, a workplace installation or a larger "
                "commercial solution, PickASparky helps you find trusted EV charger installers "
                "covering {city} and the surrounding areas.",
                max_length=600,
                help="Each town's own introduction (SEO & Locations) replaces this.",
            ),
            paragraph(
                "closing",
                "Closing line",
                "Compare up to 5 quotes from qualified electricians in {city} and find the right "
                "installer for your needs.",
                max_length=300,
                rows=2,
            ),
            text("button", "Button", "Search in Your Area", max_length=30),
        ),
    ),
)
