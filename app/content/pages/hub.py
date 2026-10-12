"""The EV charger installers hub (/uk/ev-charger-installers/)."""

from app.content.fields import (
    Document,
    faq_list,
    fixed_cards,
    image,
    paragraph,
    section,
    seo,
    text,
)

HUB = Document(
    key="installers-hub",
    label="Installers hub",
    group="Pages",
    path="/uk/ev-charger-installers/",
    description="The hub that lists every town and city, with how to choose an installer, "
    "services and FAQs.",
    sections=(
        seo(
            "EV Charger Installers Near You",
            "Find EV charger installers near you. Browse vetted local electricians by UK town "
            "or city, or enter your postcode to compare up to 5 free quotes.",
        ),
        section(
            "hero",
            "Hero",
            text("eyebrow", "Eyebrow", "EV charger installers", max_length=60),
            text("title", "Heading (H1)", "Find EV charger installers near you", max_length=100),
            paragraph(
                "lead",
                "Introduction",
                "Choose your nearest town or city, or enter your postcode to see trusted, vetted "
                "EV charger installers who cover your area.",
                max_length=300,
            ),
            image("image", "Photo", "/images/home/install-type-3.jpg"),
            text(
                "image_alt",
                "Photo description (alt text)",
                "Home EV charger mounted on a wall beside a parked electric car",
                max_length=160,
            ),
        ),
        section(
            "trust",
            "Trust strip",
            fixed_cards(
                "items",
                "Points",
                "point",
                [
                    {
                        "title": "Vetted before listing",
                        "text": "Qualifications and insurance are checked before an electrician "
                        "appears here.",
                    },
                    {
                        "title": "One request, up to 5 quotes",
                        "text": "Describe the job once and local installers reply with their "
                        "prices.",
                    },
                    {
                        "title": "Installers on your doorstep",
                        "text": "Browse by town, or let your postcode find who covers your street.",
                    },
                ],
                title_max=60,
                text_max=160,
            ),
        ),
        section(
            "towns",
            "Towns and cities",
            text("title", "Title", "EV charger installers by town and city", max_length=100),
            paragraph(
                "lead",
                "Lead",
                "Choose your nearest town or city to see the installers who cover it.",
                max_length=240,
                rows=2,
            ),
            help="The towns themselves are managed in SEO & Locations.",
        ),
        section(
            "choosing",
            "How to choose",
            text("title", "Title", "How to choose an EV charger installer", max_length=100),
            paragraph(
                "lead",
                "Lead",
                "A few things worth checking before you ask local electricians for quotes.",
                max_length=240,
                rows=2,
            ),
            fixed_cards(
                "cards",
                "Cards",
                "card",
                [
                    {
                        "title": "Check qualifications",
                        "text": "Ask which competent person scheme they belong to, such as "
                        "NICEIC or NAPIT, and whether they are OZEV-authorised if a grant "
                        "applies.",
                    },
                    {
                        "title": "Look for experience",
                        "text": "Chargers are a specialist job. Ask how many they fit each month "
                        "and which brands they know well.",
                    },
                    {
                        "title": "Compare quotes",
                        "text": "Line up two or three written quotes and check each one covers "
                        "the cable route, testing and certificate.",
                    },
                    {
                        "title": "Check insurance",
                        "text": "A good installer carries public liability cover and guarantees "
                        "their workmanship in writing.",
                    },
                ],
            ),
            text("help_title", "Help card: title", "Need help choosing?", max_length=60),
            paragraph(
                "help_text",
                "Help card: text",
                "Our step-by-step guide explains what to ask an installer and how to read their "
                "quote.",
                max_length=200,
                rows=2,
            ),
            text("help_button", "Help card: button", "View Guide", max_length=30),
        ),
        section(
            "services",
            "Services",
            text("title", "Title", "EV charger installation services", max_length=100),
            paragraph(
                "lead",
                "Lead",
                "Installers on PickASparky cover every kind of charging job, from a single "
                "driveway to a full car park.",
                max_length=240,
                rows=2,
            ),
            fixed_cards(
                "cards",
                "Services",
                "service",
                [
                    {
                        "title": "Home charger installation",
                        "text": "A wall or post charger on your drive, fitted and certified.",
                    },
                    {
                        "title": "Workplace charging",
                        "text": "Charge points for staff and visitor car parks.",
                    },
                    {
                        "title": "Charger replacement",
                        "text": "Swap a faulty or older unit for a new smart charger.",
                    },
                    {
                        "title": "Commercial installation",
                        "text": "Multi-bay and rapid charging for fleets and public sites.",
                    },
                ],
                text_max=160,
            ),
            text("link", "Link text", "Get free quotes for your job", max_length=60),
        ),
        section(
            "faq",
            "FAQ",
            text("title", "Title", "Frequently asked questions", max_length=100),
            paragraph(
                "lead",
                "Lead",
                "Short answers about finding and choosing EV charger installers in the UK.",
                max_length=240,
                rows=2,
            ),
            faq_list(
                "items",
                "Questions",
                [
                    {
                        "question": "How do I find EV charger installers near me?",
                        "answer": "Pick your town or city from the list on this page to see the "
                        "installers who cover it, or enter your postcode above. Your postcode "
                        "lets us match you with installers whose service area includes your "
                        "address, even if you live between two towns.",
                    },
                    {
                        "question": "How many quotes will I receive?",
                        "answer": "Each request goes to as many as 5 suitable installers. In busy "
                        "cities you will usually hear from several; in rural areas fewer "
                        "installers may cover your address, so you may receive one or two.",
                    },
                    {
                        "question": "How much does EV charger installation cost?",
                        "answer": "The price depends mostly on the charger you choose, the "
                        "distance between your fuse box and the charging spot, and whether your "
                        "consumer unit or earthing needs work. Comparing written quotes for the "
                        "same job is the quickest way to see a fair price for your home.",
                    },
                    {
                        "question": "What qualifications should an installer have?",
                        "answer": "Look for a registered electrician in a competent person scheme "
                        "such as NICEIC or NAPIT, who follows the IET Code of Practice for EV "
                        "charging. They should register the work with Building Control and give "
                        "you an electrical installation certificate when they finish.",
                    },
                    {
                        "question": "Do I need a qualified electrician?",
                        "answer": "Yes. A charger needs its own circuit and the right protection, "
                        "and the work must meet the wiring regulations. Only a qualified "
                        "electrician can certify the installation safely, and your warranty or "
                        "home insurance may depend on it.",
                    },
                    {
                        "question": "Can I choose a specific charger brand?",
                        "answer": "Yes. Tell installers which charger you want when you request "
                        "quotes, or ask them to recommend one. Many installers fit several "
                        "brands, and they can check the model you like suits your car and your "
                        "electricity supply.",
                    },
                ],
            ),
        ),
    ),
)
