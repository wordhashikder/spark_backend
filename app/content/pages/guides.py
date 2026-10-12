"""Guide pages: How we vet installers, Electrician accreditations, Electrical safety."""

from app.content.fields import (
    Document,
    Section,
    faq_list,
    fixed_cards,
    paragraph,
    section,
    seo,
    text,
)


def _cta(eyebrow: str, title: str, lead: str) -> Section:
    return section(
        "cta",
        "Call to action",
        text("eyebrow", "Eyebrow", eyebrow, max_length=60),
        text("title", "Title", title, max_length=100),
        paragraph("lead", "Text", lead, max_length=240, rows=2),
        text("button", "Button", "Get Free Quotes", max_length=30),
    )


VETTING = Document(
    key="how-we-vet",
    label="How we vet installers",
    group="Guides",
    path="/how-we-vet-installers/",
    description="The vetting process, what it means for homeowners and FAQs.",
    sections=(
        seo(
            "How We Vet Installers and Electricians",
            "How PickASparky vets electricians before they are listed: Companies House business "
            "checks, accreditations such as NICEIC and NAPIT, services and coverage.",
        ),
        section(
            "hero",
            "Hero",
            text("eyebrow", "Eyebrow", "How we vet installers", max_length=40),
            text(
                "title",
                "Heading (H1)",
                "Trusted electricians for your peace of mind",
                max_length=100,
            ),
            paragraph(
                "lead",
                "Introduction",
                "We know that letting someone work in your home or business is a big decision. "
                "That’s why we carefully vet all electricians before they are listed on "
                "PickASparky to make sure they are qualified, legitimate and trustworthy.",
                max_length=500,
            ),
            text("callout_title", "Callout: title", "Our commitment", max_length=60),
            paragraph(
                "callout_text",
                "Callout: text",
                "We only list genuine, qualified and reputable electricians who meet our "
                "standards. This helps you get quotes with confidence.",
                max_length=300,
            ),
        ),
        section(
            "process",
            "Vetting process",
            text("title", "Title", "Our vetting process", max_length=100),
            paragraph(
                "lead",
                "Lead",
                "Every electrician is checked using a combination of official records, "
                "qualifications and business details before they can be listed on our platform.",
                max_length=300,
            ),
            fixed_cards(
                "steps",
                "Steps",
                "step",
                [
                    {
                        "title": "Business verification",
                        "text": "We verify the electrician’s business details using Companies "
                        "House to check they are a legitimate and active company.",
                    },
                    {
                        "title": "Qualifications and accreditations",
                        "text": "We check industry accreditations such as NICEIC, NAPIT, MCS and "
                        "OZEV (where applicable) to confirm they are properly qualified.",
                    },
                    {
                        "title": "Services and experience",
                        "text": "We review the services they offer, their experience and areas "
                        "they cover to make sure they are a good match for homeowner needs.",
                    },
                    {
                        "title": "Coverage verification",
                        "text": "We confirm the areas they operate in, so you’re only matched "
                        "with electricians who genuinely work in your location.",
                    },
                    {
                        "title": "Ongoing monitoring",
                        "text": "We regularly review our listings to make sure information stays "
                        "up to date and our standards are always met.",
                    },
                ],
            ),
        ),
        section(
            "outcomes",
            "What this means for you",
            text("title", "Title", "What this means for you", max_length=100),
            paragraph(
                "lead",
                "Lead",
                "Our vetting process helps ensure you’re connected with electricians who are:",
                max_length=240,
                rows=2,
            ),
            fixed_cards(
                "items",
                "Outcomes",
                "outcome",
                [
                    {
                        "title": "Qualified and accredited",
                        "text": "Properly trained and certified for electrical work.",
                    },
                    {
                        "title": "Legitimate businesses",
                        "text": "Verified through official records.",
                    },
                    {
                        "title": "Experienced and local",
                        "text": "Providing the right services in your area.",
                    },
                    {
                        "title": "More confidence",
                        "text": "Get quotes from trusted electricians with peace of mind.",
                    },
                ],
                help="Each point has a green tick.",
            ),
        ),
        section(
            "faq",
            "FAQ",
            text("title", "Title", "Frequently asked questions", max_length=100),
            paragraph(
                "lead",
                "Lead",
                "Find answers to common questions about how we vet electricians on PickASparky.",
                max_length=240,
                rows=2,
            ),
            faq_list(
                "items",
                "Questions",
                [
                    {
                        "question": "What qualifications do you check?",
                        "answer": "We check the industry accreditations and registrations an "
                        "electrician holds, such as NICEIC, NAPIT, MCS and OZEV where they apply "
                        "to the work on offer. We ask for these details when an electrician joins "
                        "and we may request evidence before a profile is listed. Registrations "
                        "can change, so you can also confirm an electrician’s current status on "
                        "the scheme’s own register.",
                    },
                    {
                        "question": "Do you only list NICEIC or NAPIT electricians?",
                        "answer": "No. NICEIC and NAPIT are two of the most widely used schemes, "
                        "but they are not the only ones we look at. We also consider other "
                        "relevant registrations, such as MCS and OZEV where applicable. Each "
                        "profile shows the accreditations that business holds, so you can see "
                        "which ones matter for your job.",
                    },
                    {
                        "question": "Do you check that electricians are insured?",
                        "answer": "Insurance is not one of our verification checks. We ask "
                        "electricians to confirm that they hold appropriate insurance for the "
                        "work they carry out and we may request evidence, but we do not verify "
                        "or monitor individual policies. Before you hire, ask the electrician to "
                        "show you their public liability cover and, where relevant, employer’s "
                        "liability cover.",
                    },
                    {
                        "question": "How do you verify business details?",
                        "answer": "We check the business details an electrician gives us against "
                        "the official Companies House record, to confirm that the company exists "
                        "and is active. We also review the services they offer and the areas "
                        "they cover before the profile is listed.",
                    },
                    {
                        "question": "Do you carry out background checks?",
                        "answer": "Our vetting does not include criminal record (DBS) or other "
                        "personal background checks on individual electricians. It focuses on "
                        "the business: its Companies House record, its accreditations, the "
                        "services it offers and the areas it covers. If a background check "
                        "matters for your job, ask the electrician about it directly before work "
                        "starts.",
                    },
                    {
                        "question": "How often do you review listings?",
                        "answer": "We review listings regularly as part of our ongoing "
                        "monitoring, to check that the information shown is still up to date and "
                        "that our standards are still being met. We also look again at a listing "
                        "when a problem with it is reported to us.",
                    },
                    {
                        "question": "Can I report an issue with a listing?",
                        "answer": "Yes. Email {email} with the name of the electrician and a "
                        "short description of the issue. Our support team is available Monday to "
                        "Friday, 9:00am to 5:00pm UK time, and replies within 1 working day. We "
                        "will review the listing and may update or remove it.",
                    },
                ],
            ),
        ),
    ),
)

ACCREDITATIONS = Document(
    key="accreditations",
    label="Electrician accreditations",
    group="Guides",
    path="/electrician-accreditations/",
    description="The main schemes, what they tell you, other things to consider and FAQs.",
    sections=(
        seo(
            "Electrician Accreditations: NICEIC, NAPIT, MCS",
            "What NICEIC, NAPIT, TrustMark and MCS mean, what each electrician accreditation "
            "covers and how to check an electrician’s registration before you hire.",
        ),
        section(
            "hero",
            "Hero",
            text("eyebrow", "Eyebrow", "Electrician accreditations", max_length=40),
            text(
                "title",
                "Heading (H1)",
                "Understanding electrician accreditations",
                max_length=100,
            ),
            paragraph(
                "lead",
                "Introduction",
                "Registrations and certification schemes can help you understand what an "
                "electrician or electrical business has been assessed or certified for. "
                "Different schemes cover different types of work, so the most relevant "
                "accreditation depends on the job you need done.",
                max_length=500,
            ),
        ),
        section(
            "schemes",
            "Main schemes",
            text("eyebrow", "Eyebrow", "Common accreditations and schemes", max_length=60),
            text(
                "title",
                "Title",
                "The main electrician accreditations in the UK",
                max_length=100,
            ),
            paragraph(
                "lead",
                "Lead",
                "Here are some of the most common schemes you may come across when looking for "
                "an electrician. Each one assesses different areas of work and may be relevant "
                "depending on your project.",
                max_length=400,
            ),
            fixed_cards(
                "cards",
                "Schemes",
                "scheme",
                [
                    {
                        "title": "NICEIC",
                        "text": "NICEIC operates a range of schemes for electrical businesses. Its "
                        "Approved Contractor scheme assesses businesses against requirements "
                        "including BS 7671 (the IET Wiring Regulations).",
                    },
                    {
                        "title": "NAPIT",
                        "text": "NAPIT operates schemes covering electrical work, including "
                        "Competent Person Scheme membership and electrotechnical assessment "
                        "routes for businesses and individual electricians.",
                    },
                    {
                        "title": "TrustMark",
                        "text": "TrustMark is the UK Government-endorsed quality scheme for work "
                        "in and around the home. Registered businesses must meet scheme "
                        "requirements around competence, customer service and trading practices.",
                    },
                    {
                        "title": "MCS",
                        "text": "MCS certification relates to small-scale renewable and "
                        "low-carbon technologies such as solar PV, heat pumps and electrical "
                        "energy storage. This is relevant only for work involving these types of "
                        "systems.",
                    },
                ],
                text_max=400,
            ),
        ),
        section(
            "meaning",
            "What they tell you",
            text("eyebrow", "Eyebrow", "What this means for you", max_length=60),
            text(
                "title",
                "Title",
                "What do these credentials actually tell you?",
                max_length=100,
            ),
            paragraph(
                "lead",
                "Lead",
                "Accreditations can be a useful indicator, but it’s important to understand what "
                "they cover and how to use them when choosing an electrician.",
                max_length=400,
            ),
            fixed_cards(
                "cards",
                "Points",
                "point",
                [
                    {
                        "title": "Scope matters",
                        "text": "Check what specific work the business is registered or "
                        "certified for, as each scheme covers different areas.",
                    },
                    {
                        "title": "Check current status",
                        "text": "You can usually check an electrician’s or business’s "
                        "registration status on the relevant scheme’s website.",
                    },
                    {
                        "title": "Not every scheme applies",
                        "text": "The right accreditation depends on the type of work being "
                        "carried out – for example, MCS is only relevant for renewable energy "
                        "systems.",
                    },
                ],
            ),
        ),
        section(
            "consider",
            "Other things to consider",
            text("eyebrow", "Eyebrow", "Accreditation isn’t the whole picture", max_length=60),
            text("title", "Title", "Other things to consider", max_length=100),
            paragraph(
                "lead",
                "Lead",
                "While accreditations are important, there are also other factors to look at "
                "when choosing an electrician. These can help you feel confident you’re working "
                "with the right person for your project.",
                max_length=400,
            ),
            fixed_cards(
                "items",
                "Considerations",
                "item",
                [
                    {
                        "title": "Relevant experience",
                        "text": "Make sure they have experience with the type of work you need.",
                    },
                    {
                        "title": "Clear quotations",
                        "text": "Get a detailed, written quote so you know what’s included.",
                    },
                    {
                        "title": "Appropriate insurance",
                        "text": "Check they have suitable public liability insurance and, where "
                        "relevant, employer’s liability insurance.",
                    },
                    {
                        "title": "Reviews and business information",
                        "text": "Look at customer reviews and check basic business details.",
                    },
                    {
                        "title": "Right fit for your job",
                        "text": "Choose an electrician who is a good match for your specific "
                        "needs.",
                    },
                ],
            ),
        ),
        section(
            "faq",
            "FAQ",
            text("eyebrow", "Eyebrow", "Frequently asked questions", max_length=60),
            text("title", "Title", "Electrician accreditations FAQ", max_length=100),
            faq_list(
                "items",
                "Questions",
                [
                    {
                        "question": "Does every electrician need to be NICEIC registered?",
                        "answer": "No. NICEIC is one of several bodies that assess and register "
                        "electrical businesses, and registration with it is voluntary. NAPIT is "
                        "another widely used scheme. What matters is that the electrician is "
                        "qualified and registered for the type of work you need. In England and "
                        "Wales, members of a Competent Person Scheme can self-certify that "
                        "notifiable work in homes complies with the Building Regulations.",
                    },
                    {
                        "question": "What is a Competent Person Scheme?",
                        "answer": "A Competent Person Scheme is a government-authorised scheme "
                        "whose registered members can self-certify that their work complies with "
                        "the Building Regulations, instead of having it checked by local "
                        "authority building control. For electrical work in homes in England and "
                        "Wales this relates to Part P. Scheme operators include NICEIC and NAPIT. "
                        "Scotland and Northern Ireland have their own building standards.",
                    },
                    {
                        "question": "What does MCS certification cover?",
                        "answer": "MCS certification covers small-scale renewable and low-carbon "
                        "technologies, such as solar PV, heat pumps and battery storage. It is "
                        "relevant only if your job involves one of these systems. It is not a "
                        "general electrical accreditation, so an electrician does not need it "
                        "for work such as rewiring or replacing a consumer unit.",
                    },
                    {
                        "question": "What is TrustMark?",
                        "answer": "TrustMark is the UK Government-endorsed quality scheme for "
                        "work carried out in and around the home. Businesses registered with "
                        "TrustMark must meet scheme requirements covering competence, customer "
                        "service and trading practices. It covers many trades, not only "
                        "electricians, so check what a business is registered for.",
                    },
                    {
                        "question": "How can I check an electrician’s registration?",
                        "answer": "Check the scheme’s own register. NICEIC, NAPIT, TrustMark and "
                        "MCS each have a search on their website where you can look up a "
                        "registered business. Ask the electrician for their registered business "
                        "name or registration number, and make sure the registration covers the "
                        "type of work you need. Registrations can change, so the scheme’s "
                        "register is the place to confirm an electrician’s current status.",
                    },
                ],
            ),
        ),
        _cta(
            "Ready to find an electrician?",
            "Get quotes from trusted electricians",
            "Compare up to 5 quotes from vetted electricians in your area. It’s free, with no "
            "obligation.",
        ),
    ),
)

SAFETY = Document(
    key="safety",
    label="Electrical safety & regulations",
    group="Guides",
    path="/electrical-safety-regulations/",
    description="A plain-English guide to UK electrical safety rules, with FAQs.",
    sections=(
        seo(
            "Electrical Safety Regulations UK: Simple Guide",
            "A plain-English guide to UK electrical safety: Part P of the Building Regulations, "
            "BS 7671, Competent Person Schemes, EICRs and when to use an electrician.",
        ),
        section(
            "hero",
            "Hero",
            text("eyebrow", "Eyebrow", "Electrical safety & regulations", max_length=60),
            text(
                "title",
                "Heading (H1)",
                "A simple guide to UK electrical safety and regulations",
                max_length=100,
            ),
            paragraph(
                "lead",
                "Introduction",
                "Understand the key rules, standards and legal requirements for electrical work "
                "in the UK. Whether you’re a homeowner or looking for an electrician, this guide "
                "explains what you need to know to stay safe and compliant.",
                max_length=500,
            ),
        ),
        section(
            "why",
            "Why it matters",
            text("title", "Title", "Why electrical safety matters", max_length=100),
            paragraph(
                "text",
                "Text",
                "Electrical work that isn’t carried out correctly can be dangerous and may lead "
                "to electric shocks, fires or damage to property. UK regulations and standards "
                "are in place to ensure electrical installations are safe, reliable and carried "
                "out by competent people.",
                max_length=600,
            ),
            text("callout_title", "Callout: title", "Use a qualified electrician", max_length=60),
            paragraph(
                "callout_text",
                "Callout: text",
                "Always choose an electrician who is properly registered and qualified for the "
                "type of work you need.",
                max_length=300,
            ),
        ),
        section(
            "regulations",
            "Key regulations",
            text("title", "Title", "Key regulations and standards", max_length=100),
            paragraph(
                "lead",
                "Lead",
                "Electrical work in the UK is covered by a number of regulations and standards. "
                "Here are the most important ones to know about.",
                max_length=400,
            ),
            fixed_cards(
                "cards",
                "Regulations",
                "regulation",
                [
                    {
                        "title": "Building Regulations (Part P)",
                        "text": "Covers electrical safety in dwellings. Most electrical work in "
                        "homes must comply with Part P of the Building Regulations.",
                    },
                    {
                        "title": "BS 7671 (IET Wiring Regulations)",
                        "text": "The national standard for electrical installations in the UK. It "
                        "sets out the requirements for the design, installation and inspection "
                        "of electrical systems.",
                    },
                    {
                        "title": "Competent Person Schemes",
                        "text": "Schemes such as NICEIC and NAPIT allow qualified electricians to "
                        "self-certify that their work complies with Building Regulations.",
                    },
                    {
                        "title": "Electrical Installation Condition Report (EICR)",
                        "text": "A thorough inspection and test of an existing electrical "
                        "installation to assess its safety and condition. Commonly required for "
                        "rented properties and recommended for older homes.",
                    },
                ],
                text_max=400,
            ),
        ),
        section(
            "when",
            "When you need an electrician",
            text("title", "Title", "When do you need an electrician?", max_length=100),
            paragraph(
                "lead",
                "Lead",
                "You should always use a qualified electrician for:",
                max_length=240,
                rows=2,
            ),
            fixed_cards(
                "items",
                "Jobs",
                "job",
                [
                    {
                        "title": "New installations",
                        "text": "e.g. new builds, extensions or additional circuits",
                    },
                    {
                        "title": "Major electrical work",
                        "text": "e.g. rewiring, consumer unit upgrades",
                    },
                    {
                        "title": "Work in special locations",
                        "text": "e.g. bathrooms, kitchens or outdoor areas",
                    },
                    {
                        "title": "Safety inspections",
                        "text": "e.g. EICR for landlords or older properties",
                    },
                    {
                        "title": "Fault finding and repairs",
                        "text": "to keep your home or business safe",
                    },
                ],
            ),
        ),
        section(
            "faq",
            "FAQ",
            text("title", "Title", "Frequently asked questions", max_length=100),
            paragraph(
                "lead",
                "Lead",
                "Get answers to common questions about electrical safety and regulations in "
                "the UK.",
                max_length=240,
                rows=2,
            ),
            faq_list(
                "items",
                "Questions",
                [
                    {
                        "question": "What is Part P of the Building Regulations?",
                        "answer": "Part P is the part of the Building Regulations that covers "
                        "electrical safety in dwellings in England and Wales. It requires "
                        "electrical work in homes to be designed and installed so that people are "
                        "protected from fire and injury. Some types of work are notifiable, which "
                        "means they must be certified as compliant, for example by an "
                        "electrician registered with a Competent Person Scheme. Scotland and "
                        "Northern Ireland have their own building standards.",
                    },
                    {
                        "question": "Do I need a qualified electrician for small jobs?",
                        "answer": "We recommend using a qualified electrician for any work on "
                        "fixed wiring, however small. Not every small job is notifiable under the "
                        "Building Regulations, but electrical work in a home should still be "
                        "carried out safely and to BS 7671, the IET Wiring Regulations. If you "
                        "are not sure whether a job needs to be notified, ask a registered "
                        "electrician or your local authority building control before work "
                        "starts.",
                    },
                    {
                        "question": "What is an Electrical Installation Condition Report (EICR)?",
                        "answer": "An Electrical Installation Condition Report (EICR) is the "
                        "report produced after a qualified person inspects and tests the existing "
                        "electrical installation in a property. It records the condition of the "
                        "installation and notes any damage, deterioration or defects that could "
                        "be a safety risk and need attention.",
                    },
                    {
                        "question": "How often should an EICR be carried out?",
                        "answer": "It depends on the property. In the private rented sector in "
                        "England, an EICR is required at least every 5 years. For owner-occupied "
                        "homes, a periodic inspection is commonly recommended about every 10 "
                        "years, or when the occupancy changes. Other parts of the UK have their "
                        "own rules for rented homes, and the electrician carrying out the "
                        "inspection may recommend a shorter interval for an older installation.",
                    },
                    {
                        "question": "What happens if electrical work doesn’t comply with "
                        "regulations?",
                        "answer": "Non-compliant electrical work can be unsafe and may need to be "
                        "put right. Where notifiable work does not comply with the Building "
                        "Regulations, local authority building control can take enforcement "
                        "action. Missing certificates can also cause problems when you come to "
                        "sell the property.",
                    },
                    {
                        "question": "How can I check if an electrician is qualified?",
                        "answer": "Ask which scheme the electrician is registered with, then "
                        "check that scheme’s own register. Schemes such as NICEIC and NAPIT have "
                        "a search on their website where you can look up a business and confirm "
                        "its current status. Make sure the registration covers the type of work "
                        "you need, and ask for the relevant certificate when the work is "
                        "finished.",
                    },
                ],
            ),
        ),
        _cta(
            "Need a qualified electrician?",
            "Get quotes from trusted electricians",
            "Find vetted electricians in your area and get up to 5 quotes for your project.",
        ),
    ),
)
