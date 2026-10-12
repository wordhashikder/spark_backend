"""The home page."""

from app.content.fields import (
    Document,
    bullets,
    image,
    items,
    link,
    paragraph,
    section,
    seo,
    text,
)

HOME = Document(
    key="home",
    label="Home",
    group="Pages",
    path="/",
    description="The landing page: hero, installation types, why choose us, guides and the "
    "quote request band.",
    sections=(
        seo(
            "PickASparky | Compare EV Charger Installer Quotes in the UK",
            "Find trusted, vetted EV charger installers near you. Enter your postcode, compare "
            "up to 5 free quotes and choose the right electrician. No obligation.",
            full_title=True,
        ),
        section(
            "hero",
            "Hero",
            text("line1", "Heading, line 1", "Find trusted", max_length=60),
            text("line2", "Heading, line 2", "EV charger installers", max_length=60),
            text("highlight", "Heading, green line", "Compare up to 5 quotes", max_length=60),
            paragraph(
                "lead",
                "Introduction",
                "Enter your postcode and we'll connect you with trusted, local EV charger "
                "installers. It's free and there's no obligation.",
                max_length=300,
            ),
            help="The page's main heading (H1) is the three heading lines together.",
        ),
        section(
            "types",
            "Installation types",
            text("eyebrow", "Eyebrow", "Popular installation types", max_length=60),
            text("title", "Title", "What do you need an EV charger for?", max_length=100),
            items(
                "cards",
                "Cards",
                "card",
                [
                    text("title", "Title", "", max_length=60),
                    text("text", "Text", "", max_length=80),
                    image("image", "Photo", ""),
                    text("alt", "Photo description (alt text)", "", max_length=160),
                ],
                [
                    {
                        "title": "Home EV charger installation",
                        "text": "Convenient charging at home",
                        "image": "/images/home/install-type-1.jpg",
                        "alt": "Electric car charging from a wall-mounted home charger",
                    },
                    {
                        "title": "Replace an existing EV charger",
                        "text": "Upgrade to a newer, smarter charger",
                        "image": "/images/home/install-type-2.jpg",
                        "alt": "Hand plugging a cable into a wall-mounted EV charger",
                    },
                    {
                        "title": "Commercial EV charging",
                        "text": "For businesses, fleets and workplaces",
                        "image": "/images/home/install-type-3.jpg",
                        "alt": "Driver using a phone beside a commercial EV charge point",
                    },
                    {
                        "title": "Workplace EV charging",
                        "text": "For your team and company vehicles",
                        "image": "/images/home/install-type-4.jpg",
                        "alt": "Person holding an EV charging connector next to a car",
                    },
                ],
                fixed=True,
                help="Each card opens the quote form with its installation type selected.",
            ),
        ),
        section(
            "why",
            "Why choose PickASparky",
            text("title", "Title", "Why choose PickASparky?", max_length=80),
            text("quotes_eyebrow", "Quotes card: eyebrow", "Compare quotes", max_length=40),
            text("quotes_title", "Quotes card: title", "Get up to 5 quotes", max_length=60),
            paragraph(
                "quotes_text",
                "Quotes card: text",
                "Tell us what you need and receive up to 5 quotes from trusted, local EV "
                "charger installers.",
                max_length=200,
                rows=2,
            ),
            text("quotes_button", "Quotes card: button", "Get Your Quotes", max_length=30),
            text("trust_eyebrow", "Installers card: eyebrow", "Trusted installers", max_length=40),
            text(
                "trust_title",
                "Installers card: title",
                "Verified & reviewed installers",
                max_length=60,
            ),
            paragraph(
                "trust_text",
                "Installers card: text",
                "We only work with qualified, experienced and reviewed electricians.",
                max_length=200,
                rows=2,
            ),
            text("trust_button", "Installers card: button", "Find an Installer", max_length=30),
            text("local_eyebrow", "Local card: eyebrow", "Local to you", max_length=40),
            text("local_title", "Local card: title", "Find installers near you", max_length=60),
            paragraph(
                "local_text",
                "Local card: text",
                "We match you with local EV charger installers in your area for a faster, more "
                "convenient service.",
                max_length=200,
                rows=2,
            ),
            text("local_button", "Local card: button", "Search in Your Area", max_length=30),
        ),
        section(
            "guides",
            "Guides",
            text("eyebrow", "Eyebrow", "EV charger guides", max_length=60),
            text("title", "Title", "Helpful guides for your EV journey", max_length=100),
            items(
                "cards",
                "Guide cards",
                "guide",
                [
                    text("title", "Title", "", max_length=80),
                    paragraph("text", "Text", "", max_length=160, rows=2),
                    image("image", "Image", ""),
                    link(
                        "href",
                        "Link (optional)",
                        "",
                        help="e.g. a blog article: /blog/how-much-does-it-cost/",
                        required=False,
                    ),
                ],
                [
                    {
                        "title": "EV charger installation costs in the UK",
                        "text": "Find out what affects the cost and what to expect.",
                        "image": "/images/home/guide-1.jpg",
                        "href": "",
                    },
                    {
                        "title": "Best home EV chargers for 2026",
                        "text": "Compare popular models and key features.",
                        "image": "/images/home/guide-2.jpg",
                        "href": "",
                    },
                    {
                        "title": "7kW vs 22kW chargers",
                        "text": "Which charging speed is right for your home or business?",
                        "image": "/images/home/guide-3.jpg",
                        "href": "",
                    },
                    {
                        "title": "EV charger grants in the UK",
                        "text": "See what financial support may be available and how to apply.",
                        "image": "/images/home/guide-4.jpg",
                        "href": "",
                    },
                ],
                min_items=1,
                max_items=8,
            ),
        ),
        section(
            "request",
            "Quote request band",
            text("eyebrow", "Eyebrow", "Local EV charger installers", max_length=60),
            text("title", "Title", "Request Quote from Vetted Installers", max_length=100),
            paragraph(
                "lead",
                "Text",
                "Tell us where you are and compare quotes from trusted EV charger installers "
                "in your area.",
                max_length=240,
                rows=2,
            ),
            text("button", "Search button", "Search Installers", max_length=30),
            text("reasons_title", "Reasons card: title", "Why choose PickASparky?", max_length=60),
            bullets(
                "reasons",
                "Reasons",
                [
                    "Trusted, vetted installers",
                    "Real customer reviews",
                    "Compare up to 5 quotes",
                    "Simple and secure",
                    "Supporting the UK's transition to cleaner transport",
                ],
            ),
        ),
    ),
)
