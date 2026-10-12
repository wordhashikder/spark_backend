"""Policy pages: Privacy, Terms & Conditions, Cookies.

Each is a list of sections with a heading and a Markdown body, like the
policy editors of other back offices: add, reorder or remove sections freely.
"""

from typing import Any

from app.content.fields import Document, items, markdown, section, seo, text


def _policy(
    key: str,
    label: str,
    path: str,
    seo_title: str,
    seo_description: str,
    heading: str,
    updated: str,
    sections: list[dict[str, Any]],
) -> Document:
    return Document(
        key=key,
        label=label,
        group="Legal",
        path=path,
        description=f"The {label} page: its heading, date and sections.",
        sections=(
            seo(seo_title, seo_description),
            section(
                "header",
                "Header",
                text("title", "Page title (H1)", heading, max_length=80),
                text(
                    "updated",
                    "Last updated",
                    updated,
                    max_length=30,
                    help='Shown above the title, e.g. "Oct 2026". Change it when you change '
                    "the policy.",
                ),
            ),
            section(
                "body",
                "Policy sections",
                items(
                    "sections",
                    "Sections",
                    "section",
                    [
                        text("title", "Heading", "", max_length=100),
                        markdown(
                            "body",
                            "Text",
                            "",
                            max_length=8000,
                            rows=8,
                            help="Paragraphs, bullet lists (start lines with - ), **bold** and "
                            "[links](https://…). Use {privacy_email} for the privacy address.",
                        ),
                    ],
                    sections,
                    min_items=1,
                    max_items=40,
                    help='Shown in this order, with an "On this page" list built from the '
                    "headings.",
                ),
            ),
        ),
    )


def _s(title: str, body: str) -> dict[str, str]:
    return {"title": title, "body": body}


PRIVACY = _policy(
    "privacy",
    "Privacy Policy",
    "/privacy-policy/",
    "Privacy Policy",
    "How PickASparky collects, uses, shares and protects your personal information when you "
    "request EV charger installation quotes, and your UK GDPR rights.",
    "Privacy Policy",
    "Sept 2026",
    [
        _s(
            "Introduction",
            "This Privacy Policy explains how PickASparky (“we”, “us”) collects, uses and "
            "protects your personal information when you use our marketplace to request EV "
            "charger installation quotes. By using our services, you agree to the practices "
            "described below.",
        ),
        _s(
            "Data We Collect",
            "We only collect the information needed to connect you with suitable installers, "
            "including:\n\n"
            "- Contact details such as your name, email address and phone number.\n"
            "- Your postcode and property information relevant to an installation.\n"
            "- Details of the quote or service you request.\n"
            "- Technical data such as browser type, device and IP address.",
        ),
        _s(
            "How We Use It",
            "Your data is used strictly to deliver and improve our services. Specifically, we "
            "use it to:\n\n"
            "- Match your request with relevant vetted installers in your area.\n"
            "- Send you quotes, updates and service-related communications.\n"
            "- Maintain the safety, security and integrity of our platform.\n"
            "- Comply with our legal and regulatory obligations.",
        ),
        _s(
            "Data Sharing",
            "We share your details only with the installers you have chosen to request a quote "
            "from, and with trusted service providers who help us operate the platform. We never "
            "sell your personal data to third parties for marketing purposes.",
        ),
        _s(
            "Your Rights",
            "Under UK GDPR, you have the right to:\n\n"
            "- Access the personal data we hold about you.\n"
            "- Request correction or deletion of your data.\n"
            "- Object to or restrict certain processing.\n"
            "- Withdraw consent at any time.",
        ),
        _s(
            "Contact Us",
            "If you have any questions about this policy or wish to exercise your rights, please "
            "contact our data protection team at "
            "[{privacy_email}](mailto:{privacy_email}).",
        ),
    ],
)

TERMS = _policy(
    "terms",
    "Terms & Conditions",
    "/terms-and-conditions/",
    "Terms & Conditions",
    "The terms that govern your use of the PickASparky marketplace: what users and installers "
    "agree to, how quotes and payments work, and limits on our liability.",
    "Terms & Conditions",
    "Sept 2026",
    [
        _s(
            "Introduction",
            "These Terms & Conditions govern your use of the PickASparky marketplace. By "
            "accessing our website or requesting a quote, you agree to be bound by these terms. "
            "Please read them carefully before using our services.",
        ),
        _s(
            "User Agreement",
            "As a user of PickASparky, you agree to:\n\n"
            "- Provide accurate and complete information when requesting quotes.\n"
            "- Use the platform only for lawful purposes.\n"
            "- Not misuse, disrupt or attempt to gain unauthorised access to our services.\n"
            "- Be responsible for any agreements you enter into directly with an installer.",
        ),
        _s(
            "Installer Obligations",
            "Installers listed on our marketplace are independent businesses who agree to:\n\n"
            "- Hold all required accreditations, licences and insurance.\n"
            "- Provide accurate quotes and carry out work to industry standards.\n"
            "- Comply with all applicable UK electrical safety regulations.\n"
            "- Respond to customer enquiries in a professional and timely manner.",
        ),
        _s(
            "Quotes & Payments",
            "PickASparky is a lead-generation marketplace. Any quote provided is an estimate from "
            "an independent installer, and all payments and contracts are agreed directly "
            "between you and that installer. We are not a party to those agreements.",
        ),
        _s(
            "Limitation of Liability",
            "While we carefully vet the installers on our platform, PickASparky is not liable for "
            "the workmanship, conduct or contractual performance of any third-party installer. "
            "Our liability is limited to the fullest extent permitted by law.",
        ),
        _s(
            "Changes to These Terms",
            "We may update these Terms & Conditions from time to time. Any changes will be posted "
            "on this page with an updated effective date. Continued use of the platform "
            "constitutes acceptance of the revised terms.",
        ),
    ],
)

COOKIES = _policy(
    "cookies",
    "Cookie Policy",
    "/cookie-policy/",
    "Cookie Policy",
    "Which cookies the PickASparky website uses: strictly necessary cookies only, no analytics "
    "or advertising cookies, and how to control cookies in your browser.",
    "Cookie Policy",
    "Oct 2026",
    [
        _s(
            "Introduction",
            "This Cookie Policy explains what cookies are, which ones the PickASparky website "
            "uses and how you can control them. We keep cookies to a minimum: the site sets only "
            "the cookies it needs in order to work.",
        ),
        _s(
            "What Are Cookies",
            "Cookies are small text files that a website stores on your device. They let the "
            "site remember information between pages or visits, such as whether you are signed "
            "in.",
        ),
        _s(
            "Cookies We Use",
            "We use strictly necessary cookies only. These are the session cookies set when an "
            "installer signs in to their PickASparky account. They:\n\n"
            "- Keep the installer signed in as they move between pages of their account.\n"
            "- Help keep the account secure.\n\n"
            "These cookies are used only for installer accounts. Homeowners can browse the site "
            "and request quotes without signing in. Because strictly necessary cookies are "
            "essential to a service you have asked for, they are set without asking for "
            "consent.",
        ),
        _s(
            "Browser Storage",
            "The quote form uses your browser’s session storage, which works in a similar way to "
            "a cookie, to keep your answers while you fill the form in, so that refreshing the "
            "page does not lose your progress. This information is stored only in your browser, "
            "is not used to track you and is removed when you close the tab.",
        ),
        _s(
            "Analytics & Advertising",
            "We do not use analytics cookies or advertising cookies, and we do not use cookies "
            "to track you across other websites.",
        ),
        _s(
            "Third-Party Cookies",
            "Installers pay for their plan through Stripe. Stripe’s checkout and billing pages "
            "are hosted by Stripe, not by us, and Stripe sets its own cookies on those pages. "
            "Those cookies are controlled by Stripe and covered by Stripe’s own cookie policy.",
        ),
        _s(
            "Managing Cookies",
            "You can control cookies in your browser settings. Most browsers let you:\n\n"
            "- See which cookies are stored on your device and delete them.\n"
            "- Block cookies from particular websites, or from all websites.\n"
            "- Block third-party cookies.\n"
            "- Clear all cookies when you close the browser.\n\n"
            "Your browser’s help pages explain where to find these settings. If you block or "
            "delete our strictly necessary cookies, installers will not be able to stay signed "
            "in to their account. If you block browser storage, the quote form still works but "
            "will not remember your answers if you refresh the page.",
        ),
        _s(
            "Changes to This Policy",
            "If we add analytics or any other non-essential cookies in future, we will update "
            "this policy and ask for your consent where the law requires it. The date at the top "
            "of this page shows when the policy was last updated.",
        ),
        _s(
            "Contact Us",
            "If you have any questions about how we use cookies, please contact us at "
            "[{privacy_email}](mailto:{privacy_email}). Our [Privacy Policy](/privacy-policy/) "
            "explains how we handle personal information more generally.",
        ),
    ],
)
