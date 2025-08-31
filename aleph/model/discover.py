"""Pre-computed Dataset discovery analysis"""

from pydantic import BaseModel, computed_field


class Term(BaseModel):
    name: str
    count: int = 0

    @computed_field
    @property
    def label(self) -> str:
        return self.name.title()


class MentionedTerms(BaseModel):
    peopleMentioned: list[Term] = []
    companiesMentioned: list[Term] = []
    locationMentioned: list[Term] = []
    namesMentioned: list[Term] = []


class SignificantTerms(MentionedTerms):
    term: Term


class DatasetDiscovery(BaseModel):
    name: str  # collection foreign_id
    peopleMentioned: list[SignificantTerms] = []
    companiesMentioned: list[SignificantTerms] = []
    locationMentioned: list[SignificantTerms] = []
    namesMentioned: list[SignificantTerms] = []
