"""How a homeowner's name is shown to installers.

Homeowners may type their full name into the quote or enquiry form. The full name is kept as
typed, for the homeowner and the PickASparky team. Installers only ever see the first name:
a full name is enough to find a person on social media and approach them without going
through (or paying) PickASparky. Every installer-facing screen and email goes through the two
functions below, so the rule lives in one place.
"""

import re

# A leading title is not a first name: "Mr John Smith" is shown as "John".
_TITLES = frozenset({"mr", "mrs", "ms", "miss", "mx", "dr", "prof"})
_SPACES = re.compile(r"\s+")


def given_name(full_name: str) -> str:
    """The first name from whatever the homeowner typed ("Jane Doe" -> "Jane")."""
    words = _SPACES.sub(" ", full_name).strip().split(" ")
    if len(words) > 1 and words[0].rstrip(".").lower() in _TITLES:
        words = words[1:]
    return words[0].strip(",;") if words[0] else ""


def hide_surname(text: str, full_name: str) -> str:
    """`text` with the homeowner's full name replaced by their first name.

    For lines the system wrote itself ("Jane Doe accepted quote ..."), including any saved
    before this rule existed.
    """
    short = given_name(full_name)
    for variant in {full_name.strip(), _SPACES.sub(" ", full_name).strip()}:
        if variant and variant != short:
            text = text.replace(variant, short)
    return text
