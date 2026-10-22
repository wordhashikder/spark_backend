"""The plan catalogue as the rest of the app sees it.

Plans live in the database (Dashboard > Plans & billing). Code that decides what an
installer may do, and the SQL that ranks installers, cannot await a query on every call, so
each worker keeps an in-memory snapshot of the catalogue here. It is loaded at start-up,
replaced straight after an edit in the same worker, and re-read every few seconds so edits
made through another worker are picked up too (see `services/plans.py`).
"""

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import ColumnElement, case

DEFAULT_PLAN_KEY = "free"


@dataclass(frozen=True, slots=True)
class PlanCapabilities:
    # Full access to matched enquiries: see every detail and reply with messages and quotes.
    # Every approved installer is *notified* of a matching enquiry whatever the plan; those
    # without this capability are asked to upgrade before they can open and answer it.
    receives_leads: bool
    accepts_direct_quotes: bool
    full_public_profile: bool
    public_service_limit: int | None
    sort_rank: int
    max_gallery_photos: int


@dataclass(frozen=True, slots=True)
class PlanEntry:
    key: str
    name: str
    tagline: str | None
    features: tuple[str, ...]
    is_default: bool
    is_active: bool
    is_popular: bool
    capabilities: PlanCapabilities
    # The current monthly price, if the plan can be bought.
    price_pence: int | None
    currency: str

    @property
    def is_purchasable(self) -> bool:
        return self.is_active and not self.is_default and self.price_pence is not None


# Used only until the first load (and if the database cannot be read): the most restrictive
# plan, so nothing is granted by accident.
_FALLBACK = PlanEntry(
    key=DEFAULT_PLAN_KEY,
    name="Free",
    tagline=None,
    features=(),
    is_default=True,
    is_active=True,
    is_popular=False,
    capabilities=PlanCapabilities(
        receives_leads=False,
        accepts_direct_quotes=False,
        full_public_profile=False,
        public_service_limit=2,
        sort_rank=0,
        max_gallery_photos=0,
    ),
    price_pence=None,
    currency="gbp",
)


class PlanRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, PlanEntry] = {_FALLBACK.key: _FALLBACK}
        self._default: PlanEntry = _FALLBACK

    def replace(self, entries: Iterable[PlanEntry]) -> None:
        loaded = {entry.key: entry for entry in entries}
        default = next((entry for entry in loaded.values() if entry.is_default), None)
        if default is None:
            # Never swap in a catalogue with no fallback plan.
            return
        # Assigned together so a reader never sees a new catalogue with an old default.
        self._entries, self._default = loaded, default

    @property
    def default(self) -> PlanEntry:
        return self._default

    def get(self, key: str | None) -> PlanEntry | None:
        return self._entries.get(key) if key else None

    def entry(self, key: str | None) -> PlanEntry:
        """The plan for `key`; the default plan when the key is unknown to this worker."""
        return self.get(key) or self._default

    def all(self) -> list[PlanEntry]:
        return sorted(
            self._entries.values(), key=lambda entry: (entry.capabilities.sort_rank, entry.key)
        )


registry = PlanRegistry()


def capabilities_for(plan_key: str | None) -> PlanCapabilities:
    return registry.entry(plan_key).capabilities


def lead_receiving_plan_keys() -> list[str]:
    """Plans that give full access to matched enquiries."""
    return [entry.key for entry in registry.all() if entry.capabilities.receives_leads]


def sort_rank_expression(plan_column: ColumnElement[str]) -> ColumnElement[int]:
    """SQL expression yielding the listing rank of the plan stored in `plan_column`."""
    ranks = {entry.key: entry.capabilities.sort_rank for entry in registry.all()}
    return case(ranks, value=plan_column, else_=0)
