"""Pre-computed dataset discovery analysis.

These are computed views over a :class:`Collection` (the
``CollectionDiscovery`` aggregate sits in the resolver cache under
``CollectionDiscovery/<collection_id>`). The inner ``Term`` /
``MentionedTerms`` / ``SignificantTerms`` models are nested-only and
never cached on their own – they inherit from :class:`APIBaseModel`
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


class CollectionDiscovery(APIBaseModel):
    """Resolver-cached aggregate keyed under
    ``CollectionDiscovery/<collection_id>``."""

    collection_id: str
    peopleMentioned: list[SignificantTerms] = []
    companiesMentioned: list[SignificantTerms] = []
    locationMentioned: list[SignificantTerms] = []
    namesMentioned: list[SignificantTerms] = []

    @property
    def cache_key(self) -> str:
        return self.collection_id
