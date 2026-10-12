"""Company pages: Contact, About and How it works."""

from app.content.fields import (
    Document,
    bullets,
    fixed_cards,
    image,
    paragraph,
    section,
    seo,
    text,
)

CONTACT = Document(
    key="contact",
    label="Contact",
    group="Pages",
    path="/contact/",
    description="Contact details, the contact form's heading and what to expect.",
    sections=(
        seo(
            "Contact Us: Homeowner and Electrician Support",
            "Contact PickASparky about quotes, joining as an electrician or your account. "
            "Email {email}. We aim to reply within 1 working day.",
        ),
        section(
            "hero",
            "Heading",
            text("eyebrow", "Eyebrow", "Contact us", max_length=40),
            text("title", "Heading (H1)", "We're here to help", max_length=60),
            paragraph(
                "lead",
                "Introduction",
                "Have a question about getting quotes, joining as an electrician or anything "
                "else? Get in touch and we'll be happy to help.",
                max_length=300,
            ),
            help="The email address and hours come from Settings › Organisation and "
            "Site-wide content.",
        ),
        section(
            "details",
            "Contact details",
            text("email_title", "Email: title", "Email us", max_length=40),
            paragraph(
                "email_text",
                "Email: text",
                "For general enquiries, support or partnership opportunities.",
                max_length=160,
                rows=2,
            ),
            text("hours_title", "Hours: title", "Our hours", max_length=40),
        ),
        section(
            "promises",
            "What to expect",
            fixed_cards(
                "items",
                "Promises",
                "promise",
                [
                    {
                        "title": "Quick response",
                        "text": "We aim to reply to all enquiries within 1 working day.",
                    },
                    {
                        "title": "Friendly support",
                        "text": "Our team is here to help homeowners and electricians.",
                    },
                    {
                        "title": "For homeowners and electricians",
                        "text": "Get the information you need about quotes, listings and "
                        "memberships.",
                    },
                ],
                title_max=60,
                text_max=160,
            ),
        ),
    ),
)

ABOUT = Document(
    key="about",
    label="About",
    group="Pages",
    path="/about/",
    description="Who PickASparky is, what it does differently and what it isn't.",
    sections=(
        seo(
            "About Us: The UK Electrician Marketplace",
            "PickASparky is an independent UK marketplace that helps homeowners and businesses "
            "find, compare and get quotes from suitable electricians in their area.",
        ),
        section(
            "hero",
            "Hero",
            text("eyebrow", "Eyebrow", "About PickASparky", max_length=40),
            text(
                "title",
                "Heading (H1)",
                "Making it easier to find the right electrician",
                max_length=100,
            ),
            paragraph(
                "lead",
                "Introduction",
                "PickASparky is an independent UK marketplace that connects homeowners and "
                "businesses with electricians. Our goal is to make it simpler to find, compare "
                "and get quotes from suitable electricians in your area.",
                max_length=400,
            ),
            image("image", "Photo", "/images/about/hero-electrician.jpg"),
            text(
                "image_alt",
                "Photo description (alt text)",
                "Smiling electrician on a stepladder fitting a ceiling light in a home",
                max_length=160,
            ),
        ),
        section(
            "why",
            "Why we built PickASparky",
            text("eyebrow", "Eyebrow", "Why we built PickASparky", max_length=60),
            text(
                "title",
                "Title",
                "Finding a good electrician shouldn’t be this difficult.",
                max_length=100,
            ),
            paragraph(
                "text",
                "Text",
                "Searching for an electrician often means checking multiple websites, "
                "contacting businesses one by one and trying to work out who covers your area "
                "and provides the service you need.",
                max_length=500,
            ),
            image("image", "Photo", "/images/about/homeowner-searching.jpg"),
            text(
                "image_alt",
                "Photo description (alt text)",
                "Homeowner at a desk searching for an electrician on a laptop",
                max_length=160,
            ),
        ),
        section(
            "different",
            "What we do differently",
            text("eyebrow", "Eyebrow", "What we’re trying to do differently", max_length=60),
            text("title", "Title", "A more transparent and useful marketplace", max_length=100),
            fixed_cards(
                "cards",
                "Cards",
                "card",
                [
                    {
                        "title": "Better information",
                        "text": "Useful electrician profiles instead of just a business name and "
                        "phone number.",
                    },
                    {
                        "title": "Relevant matches",
                        "text": "Connect customers with electricians who provide the service you "
                        "need and cover your area.",
                    },
                    {
                        "title": "More transparency",
                        "text": "Make services, coverage and relevant accreditations easier to "
                        "understand.",
                    },
                    {
                        "title": "Customer control",
                        "text": "You decide who you want to contact and who you ultimately "
                        "choose to hire.",
                    },
                ],
            ),
        ),
        section(
            "electricians",
            "Built for electricians",
            text("eyebrow", "Eyebrow", "Built for electricians too", max_length=60),
            text("title", "Title", "Supporting independent electricians", max_length=100),
            paragraph(
                "lead",
                "Text",
                "PickASparky helps electricians connect with customers looking for the services "
                "they provide in the areas they cover. It’s a straightforward way to showcase "
                "your business, share your services and reach relevant customers.",
                max_length=400,
            ),
            text("button", "Button", "Join PickASparky", max_length=30),
            image("image", "Photo", "/images/about/independent-electrician.jpg"),
            text(
                "image_alt",
                "Photo description (alt text)",
                "Electrician working on the wiring of a consumer unit",
                max_length=160,
            ),
        ),
        section(
            "trust",
            "Trust & transparency",
            text("eyebrow", "Eyebrow", "Trust & transparency", max_length=60),
            text(
                "title",
                "Title",
                "Making electrician information easier to understand",
                max_length=100,
            ),
            paragraph(
                "text",
                "Text",
                "Electrician profiles can display relevant accreditations and registrations so "
                "you can make a more informed choice. We also explain what common accreditations "
                "mean, such as NICEIC, NAPIT, TrustMark and others.",
                max_length=500,
            ),
            text(
                "link",
                "Link text",
                "Learn about electrician accreditations",
                max_length=60,
            ),
        ),
        section(
            "cta",
            "Call to action",
            text("eyebrow", "Eyebrow", "Ready to find an electrician?", max_length=60),
            text(
                "title",
                "Title",
                "Get quotes from trusted electricians in your area",
                max_length=100,
            ),
            text("button", "Button", "Get Free Quotes", max_length=30),
            text("footnote", "Electricians line", "Are you an electrician?", max_length=60),
            text("footnote_link", "Electricians link", "Join PickASparky", max_length=40),
        ),
        section(
            "isnt",
            "What PickASparky isn't",
            text("eyebrow", "Eyebrow", "What PickASparky isn’t", max_length=60),
            text("title", "Title", "We’re not an electrical contractor.", max_length=100),
            paragraph(
                "text",
                "Text",
                "PickASparky is an independent marketplace. We don’t carry out electrical work "
                "ourselves and we don’t choose an electrician on your behalf. Our role is to make "
                "it easier to discover, compare and connect with electricians.",
                max_length=500,
            ),
            fixed_cards(
                "items",
                "Points",
                "point",
                [
                    {
                        "title": "We don’t carry out electrical work",
                        "text": "PickASparky doesn’t provide electrical services and we don’t "
                        "employ electricians.",
                    },
                    {
                        "title": "We don’t choose an electrician for you",
                        "text": "You stay in control and decide who you want to contact and hire.",
                    },
                    {
                        "title": "We help you discover, compare and connect",
                        "text": "Our role is to make it easier to find suitable electricians and "
                        "get the information you need.",
                    },
                ],
            ),
        ),
    ),
)

HOW_IT_WORKS = Document(
    key="how-it-works",
    label="How it works",
    group="Pages",
    path="/how-it-works/",
    description="The steps for homeowners and for electricians.",
    sections=(
        seo(
            "How It Works for Homeowners and Electricians",
            "See how PickASparky works: homeowners enter a postcode and compare up to 5 free "
            "quotes from vetted electricians, and installers build a profile to win work.",
        ),
        section(
            "hero",
            "Hero",
            text("eyebrow", "Eyebrow", "How it works", max_length=40),
            text(
                "title",
                "Heading (H1)",
                "A simple way to connect homeowners and electricians",
                max_length=100,
            ),
            paragraph(
                "lead",
                "Introduction",
                "PickASparky makes it easy to find and compare electricians in your area. "
                "Whether you need electrical work at home or want to join as an installer, "
                "here's how it works.",
                max_length=400,
            ),
        ),
        section(
            "homeowners",
            "For homeowners",
            text("eyebrow", "Eyebrow", "For homeowners", max_length=40),
            text("title", "Title", "How it works for homeowners", max_length=100),
            paragraph(
                "lead",
                "Lead",
                "Tell us what you need, receive quotes from suitable electricians and choose who "
                "you want to work with. It's free, with no obligation, and you stay in control.",
                max_length=400,
            ),
            fixed_cards(
                "steps",
                "Steps",
                "step",
                [
                    {
                        "title": "Tell us what you need",
                        "text": "Enter your postcode and answer a few questions about the work "
                        "you need.",
                    },
                    {
                        "title": "Receive quotes",
                        "text": "Your request is sent to suitable electricians in your area who "
                        "can respond with their quotes.",
                    },
                    {
                        "title": "Choose your electrician",
                        "text": "Compare the quotes and information, and choose the electrician "
                        "you want to work with.",
                    },
                ],
            ),
            bullets("claims", "Claims", ["Free to use", "No obligation", "You stay in control"]),
            text("button", "Button", "Get Free Quotes", max_length=30),
        ),
        section(
            "electricians",
            "For electricians",
            text("eyebrow", "Eyebrow", "For electricians", max_length=40),
            text("title", "Title", "How it works for electricians", max_length=100),
            paragraph(
                "lead",
                "Lead",
                "Join PickASparky to connect with homeowners and businesses looking for "
                "electrical services in your area. Create your profile, showcase your services "
                "and start receiving relevant enquiries.",
                max_length=400,
            ),
            fixed_cards(
                "steps",
                "Steps",
                "step",
                [
                    {
                        "title": "Join as an installer",
                        "text": "Create an installer account and add your business details.",
                    },
                    {
                        "title": "Build your profile",
                        "text": "Showcase your services, areas covered, accreditations and "
                        "business information.",
                    },
                    {
                        "title": "Receive enquiries",
                        "text": "Get enquiries from homeowners and businesses looking for the "
                        "services you provide.",
                    },
                ],
            ),
            bullets(
                "claims",
                "Claims",
                ["Reach new customers", "Showcase your services", "Grow your business"],
            ),
            text("button", "Button", "Join as an Installer", max_length=30),
        ),
    ),
)
