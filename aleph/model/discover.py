"""Pre-computed dataset discovery analysis.

These are computed views over a :class:`Collection` (the
``DatasetDiscovery`` aggregate sits in the resolver cache under
``DatasetDiscovery/<foreign_id>/discovery``). The inner ``Term`` /
``MentionedTerms`` / ``SignificantTerms`` models are nested-only and
never cached on their own — they inherit from :class:`APIBaseModel`
just for the consistent ``model_dump`` semantics.
"""

from pydantic import computed_field

from aleph.model.common import APIBaseModel


class Term(APIBaseModel):
    name: str
    count: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def label(self) -> str:
        return self.name.title()


class MentionedTerms(APIBaseModel):
    peopleMentioned: list[Term] = []
    companiesMentioned: list[Term] = []
    locationMentioned: list[Term] = []
    namesMentioned: list[Term] = []


class SignificantTerms(MentionedTerms):
    term: Term


class DatasetDiscovery(APIBaseModel):
    """Resolver-cached aggregate keyed under
    ``DatasetDiscovery/<foreign_id>/discovery``."""

    name: str  # collection foreign_id
    peopleMentioned: list[SignificantTerms] = []
    companiesMentioned: list[SignificantTerms] = []
    locationMentioned: list[SignificantTerms] = []
    namesMentioned: list[SignificantTerms] = []

    @classmethod
    def make_cache_key(cls, foreign_id: str) -> str:
        return f"{foreign_id}/discovery"

    @property
    def cache_key(self) -> str:
        return self.make_cache_key(self.name)
