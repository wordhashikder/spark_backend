"""FAQ and Join pages."""

from app.content.fields import (
    Document,
    bullets,
    faq_list,
    fixed_cards,
    image,
    paragraph,
    section,
    seo,
    text,
)

_SUPPORT = {
    "question": "Who can I contact for support?",
    "answer": "Email {email} and our support team will help. We are available Monday to Friday, "
    "9:00am to 5:00pm UK time, and aim "
    "to reply within 1 working day. You can also send us a message from the Contact page.",
}
_JOIN = {
    "question": "How do I join PickASparky as an electrician?",
    "answer": "You join by creating an installer account and choosing a membership plan. Then "
    "build your profile with your business details, services, coverage area and accreditations. "
    "We review your information to verify your business before your listing goes live.",
}
_COST = {
    "question": "Is there a cost to join?",
    "answer": "No, joining is free: the Free plan costs {price_free} and gets your business "
    "listed. Paid plans add more, with Pro at {price_pro} and Premium at {price_premium}. "
    "Payments are handled by Stripe and there are no long-term contracts.",
}
_ENQUIRIES = {
    "question": "How do I receive enquiries?",
    "answer": "We notify you when a homeowner in your coverage area requests quotes. Each enquiry "
    "includes the details of the job and the homeowner's contact details so you can respond with "
    "a quote. Receiving and responding to enquiries is included in the Pro and Premium plans.",
}
_PROFILE = {
    "question": "What information should I include in my profile?",
    "answer": "Include your business details, the services you offer, the areas you cover and "
    "your accreditations, such as NICEIC, NAPIT, MCS or OZEV. A clear description, your years of "
    "experience and photos of recent work help homeowners compare you with other installers. "
    "Accurate details also help us verify your business.",
}
_ACCEPT = {
    "question": "Do I have to accept every enquiry?",
    "answer": "No, you decide which enquiries to respond to. There is no obligation to quote for "
    "every request, so you can take on new work when it suits your availability.",
}

FAQ = Document(
    key="faq",
    label="FAQ",
    group="Pages",
    path="/faq/",
    description="Questions and answers for homeowners and for electricians.",
    sections=(
        seo(
            "FAQs for Homeowners and Electricians",
            "Answers to common questions about PickASparky: free quotes for homeowners, how "
            "installers are vetted, how your details are shared and how electricians join.",
        ),
        section(
            "hero",
            "Hero",
            text("eyebrow", "Eyebrow", "FAQ", max_length=40),
            text("title", "Heading (H1)", "Frequently Asked Questions", max_length=100),
            paragraph(
                "lead",
                "Introduction",
                "Find answers to common questions from homeowners and electricians. If you "
                "can't find what you're looking for, feel free to get in touch.",
                max_length=400,
                help='The words "get in touch" link to the Contact page.',
            ),
        ),
        section(
            "homeowners",
            "For homeowners",
            text("eyebrow", "Eyebrow", "For homeowners", max_length=40),
            text("title", "Title", "Frequently asked questions for homeowners", max_length=100),
            paragraph(
                "lead",
                "Lead",
                "Everything you need to know about finding and comparing electricians through "
                "PickASparky.",
                max_length=240,
                rows=2,
            ),
            faq_list(
                "items",
                "Questions",
                [
                    {
                        "question": "Is PickASparky free to use for homeowners?",
                        "answer": "Yes, PickASparky is free for homeowners. There is no charge to "
                        "request or compare quotes and no obligation to accept any of them. You "
                        "only pay the electrician you choose, for the work you agree with them.",
                    },
                    {
                        "question": "How does PickASparky work?",
                        "answer": "PickASparky matches your request with up to 5 vetted, local "
                        "installers so you can compare quotes. Enter your postcode, answer six "
                        "short questions about the work and add your contact details. We pass "
                        "your request to installers whose service area covers your postcode, and "
                        "you choose who to work with.",
                    },
                    {
                        "question": "How many quotes will I receive?",
                        "answer": "You can receive up to 5 quotes for each request. We match your "
                        "request with up to 5 installers whose service area covers your "
                        "postcode, so the exact number depends on how many suitable installers "
                        "are available near you and how many respond.",
                    },
                    {
                        "question": "Do you share my contact details with electricians?",
                        "answer": "Yes, but only with the installers matched to your request. "
                        "They need your details to respond with a quote, and you give your "
                        "consent before the request is sent. If you ask for a quote from an "
                        "installer's profile page, your details go to that installer only.",
                    },
                    {
                        "question": "Am I obligated to hire an electrician?",
                        "answer": "No, there is no obligation to hire anyone. Requesting quotes "
                        "is free, and you can accept one, ask for more information or decide "
                        "not to go ahead at all.",
                    },
                    {
                        "question": "Are the electricians vetted?",
                        "answer": "Yes, installers are vetted before they receive enquiries "
                        "through PickASparky. Our checks cover business verification through "
                        "Companies House, qualifications and accreditations (such as NICEIC, "
                        "NAPIT, MCS and OZEV where applicable), services and experience, and "
                        "coverage area, followed by ongoing monitoring. We still recommend "
                        "confirming an installer's credentials yourself before work begins.",
                    },
                    {
                        "question": "What types of electrical work can I get quotes for?",
                        "answer": "You can request quotes for EV charger installation: a new "
                        "home charger, replacing or adding to an existing charger, and workplace "
                        "or commercial charging. Installers can also list other electrical "
                        "services on their profile, such as domestic and commercial electrical "
                        "work, repairs, solar and battery storage, smart home installations, and "
                        "EICR and testing.",
                    },
                    {
                        "question": "How quickly will I receive quotes?",
                        "answer": "Response times vary by installer, but your request is sent to "
                        "matched installers as soon as you submit it. How quickly each one "
                        "replies depends on their availability, so we can't promise an exact "
                        "time. Telling us when you would like the work done helps installers "
                        "prioritise your request.",
                    },
                    {
                        "question": "Can I choose which electrician to work with?",
                        "answer": "Yes, the choice is always yours. PickASparky does not pick an "
                        "electrician for you: you compare the quotes, reviews and "
                        "accreditations, then decide who to hire.",
                    },
                    {
                        "question": "What if I have a problem after the work is completed?",
                        "answer": "Contact the electrician who carried out the work first, "
                        "because your agreement for the work is with them. PickASparky is an "
                        "independent marketplace that does not carry out electrical work or "
                        "employ electricians. If the issue is not resolved, the installer's "
                        "accreditation scheme may be able to help through its complaints "
                        "process, and you can tell us at {email} so we can take it into account "
                        "in our ongoing monitoring.",
                    },
                ],
            ),
        ),
        section(
            "electricians",
            "For electricians",
            text("eyebrow", "Eyebrow", "For electricians", max_length=40),
            text("title", "Title", "Frequently asked questions for electricians", max_length=100),
            paragraph(
                "lead",
                "Lead",
                "Learn more about joining PickASparky and how it works for electricians.",
                max_length=240,
                rows=2,
            ),
            faq_list(
                "items",
                "Questions",
                [
                    _JOIN,
                    _COST,
                    _ENQUIRIES,
                    _PROFILE,
                    {
                        "question": "Can I choose the types of jobs I receive?",
                        "answer": "Yes, you choose the types of work you want to receive "
                        "enquiries for. Select the services you offer on your profile, from EV "
                        "charger installations to domestic, commercial and other electrical "
                        "work, and set the area you cover.",
                    },
                    _ACCEPT,
                    {
                        "question": "How are homeowners' details shared?",
                        "answer": "A homeowner's contact details are shared only with the "
                        "installers matched to their request, with the homeowner's consent. When "
                        "a homeowner requests a quote from your profile page, their details are "
                        "sent to you alone. Please use them only to respond to that enquiry.",
                    },
                    {
                        "question": "What areas can I cover?",
                        "answer": "You can cover any part of the UK that your business is able "
                        "to serve. Your coverage area is set as part of your profile, and we "
                        "match you with requests from postcodes inside it. Coverage is checked "
                        "when we verify your business.",
                    },
                    {
                        "question": "Can I update my profile later?",
                        "answer": "Yes, you can update your profile after you join. Keep your "
                        "services, coverage area and accreditations up to date so homeowners "
                        "see accurate information. If you need help making a change, email "
                        "{email}.",
                    },
                    _SUPPORT,
                ],
            ),
        ),
    ),
)

JOIN = Document(
    key="join",
    label="Join as an installer",
    group="Pages",
    path="/join/",
    description="The page that invites electricians to join: benefits, steps, work types, "
    "membership and FAQs.",
    sections=(
        seo(
            "Electrician Leads: Join as an Installer",
            "Join PickASparky to get enquiries from homeowners looking for vetted electricians in "
            "your area. Free listing, plans from {lowest_price} a month, no long-term contracts.",
        ),
        section(
            "hero",
            "Hero",
            text("eyebrow", "Eyebrow", "Join as an electrician", max_length=40),
            text(
                "title",
                "Heading (H1)",
                "Get more qualified leads for your electrical business",
                max_length=100,
            ),
            paragraph(
                "lead",
                "Introduction",
                "Join PickASparky and receive enquiries from homeowners looking for trusted, "
                "vetted electricians in your area. It's a simple and cost-effective way to grow "
                "your business.",
                max_length=400,
            ),
            text("button", "Button", "Join as an Installer", max_length=30),
            bullets(
                "claims",
                "Claims",
                ["Quality, local enquiries", "No long-term contracts", "Easy to get started"],
            ),
            image("image", "Photo", "/images/join/hero-electrician.jpg"),
            text(
                "image_alt",
                "Photo description (alt text)",
                "Smiling electrician in a hard hat with examples of new customer enquiries",
                max_length=160,
            ),
        ),
        section(
            "benefits",
            "Benefits",
            fixed_cards(
                "items",
                "Benefits",
                "benefit",
                [
                    {
                        "title": "Reach local customers",
                        "text": "Get enquiries from homeowners in your area who are actively "
                        "looking for an electrician.",
                    },
                    {
                        "title": "Quality, relevant leads",
                        "text": "Receive genuine enquiries that match your services and location.",
                    },
                    {
                        "title": "You stay in control",
                        "text": "Choose the types of jobs you receive and when you're available "
                        "to take on new work.",
                    },
                    {
                        "title": "Grow your business",
                        "text": "A simple and affordable way to get more work and build your "
                        "reputation.",
                    },
                ],
            ),
        ),
        section(
            "steps",
            "How it works",
            text("title", "Title", "How it works", max_length=100),
            paragraph(
                "lead",
                "Lead",
                "Getting started is quick and easy. Here's how it works:",
                max_length=240,
                rows=2,
            ),
            fixed_cards(
                "items",
                "Steps",
                "step",
                [
                    {
                        "title": "Create your profile",
                        "text": "Tell us about your business, services, coverage areas and "
                        "accreditations.",
                    },
                    {
                        "title": "Get verified",
                        "text": "We review your information to make sure you're a qualified and "
                        "legitimate electrician.",
                    },
                    {
                        "title": "Start receiving enquiries",
                        "text": "Get notified when homeowners in your area request quotes for "
                        "electrical work.",
                    },
                    {
                        "title": "Win more work",
                        "text": "Contact interested customers, provide your quote and grow your "
                        "business.",
                    },
                ],
            ),
        ),
        section(
            "work",
            "Types of work",
            text("title", "Title", "What types of work can you receive?", max_length=100),
            paragraph(
                "lead",
                "Lead",
                "Choose the types of electrical work you want to receive enquiries for.",
                max_length=240,
                rows=2,
            ),
            fixed_cards(
                "items",
                "Work types",
                "work type",
                [
                    {
                        "title": "Domestic electrical work",
                        "text": "Rewiring, lighting, consumer units and more.",
                    },
                    {
                        "title": "EV charger installations",
                        "text": "Home and commercial EV charging points.",
                    },
                    {"title": "Electrical repairs", "text": "Fault finding and safe repairs."},
                    {
                        "title": "Commercial projects",
                        "text": "Offices, shops, landlords and more.",
                    },
                    {
                        "title": "Additional services",
                        "text": "Solar PV, battery storage, smart home installations and more.",
                    },
                ],
            ),
        ),
        section(
            "plans",
            "Membership",
            text("title", "Title", "Membership options", max_length=100),
            paragraph(
                "lead",
                "Lead",
                "Choose the plan that works for your business. Simple and transparent pricing.",
                max_length=240,
                rows=2,
            ),
            help="Plan names, prices and features match the Stripe billing setup, so they are "
            "changed with the developers rather than here.",
        ),
        section(
            "faq",
            "FAQ",
            text("title", "Title", "Frequently asked questions", max_length=100),
            faq_list("items", "Questions", [_JOIN, _ACCEPT, _COST, _PROFILE, _ENQUIRIES, _SUPPORT]),
        ),
    ),
)
