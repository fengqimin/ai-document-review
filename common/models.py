from pydantic import BaseModel, ConfigDict, model_validator
from enum import Enum
from typing import Optional


class Location(BaseModel):
    source_sentence: str
    page_num: int
    bounding_box: list[float]
    para_index: int


class IssueType(str, Enum):
    GrammarSpelling = 'Grammar & Spelling'
    DefinitiveLanguage = 'Definitive Language'


class SingleShotIssue(BaseModel):
    type: IssueType
    location: Location
    text: str
    explanation: str
    suggested_fix: str
    comment_id: str

    @model_validator(mode="before")
    @classmethod
    def _fill_mechanical_fields(cls, data):
        """Tolerate omitted mechanical fields.

        page_num / bounding_box / comment_id are computed by the pipeline
        (add_bounding_box, dedup) and carry no meaning from the model, yet large
        models routinely leave them out. Rejecting the whole finding for a
        missing placeholder discards a valid issue and burns the retry budget.
        """
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if not isinstance(data.get("comment_id"), str):
            data["comment_id"] = ""
        location = data.get("location")
        if isinstance(location, dict):
            location = dict(location)
            if not isinstance(location.get("page_num"), int):
                location["page_num"] = 0
            if not isinstance(location.get("bounding_box"), list):
                location["bounding_box"] = []
            data["location"] = location
        return data


class ConsolidatorIssue(BaseModel):
    comment_id: str
    score: int
    suggested_action: str
    reason_for_suggested_action: str


class CombinedIssue(SingleShotIssue, ConsolidatorIssue):
    pass


class AllSingleShotIssues(BaseModel):
    issues: list[SingleShotIssue]


class AllConsolidatorIssues(BaseModel):
    issues: list[ConsolidatorIssue]


class AllCombinedIssues(BaseModel):
    issues: list[CombinedIssue]


class BaseIssue(BaseModel):
    type: IssueType
    location: Location
    text: str
    explanation: str
    suggested_fix: str


class FlowOutputChunk(BaseModel):
    issues: list[BaseIssue]


class IssueStatusEnum(str, Enum):
    accepted = 'accepted'
    dismissed = 'dismissed'
    not_reviewed = 'not_reviewed'


class ModifiedFieldsModel(BaseModel):
    suggested_fix: Optional[str] = None
    explanation: Optional[str] = None


class DismissalFeedbackModel(BaseModel):
    reason: Optional[str] = None


class Issue(BaseModel):
    id: str
    doc_id: str
    text: str
    type: IssueType
    status: IssueStatusEnum
    suggested_fix: str
    explanation: str
    location: Optional[Location] = None
    review_initiated_by: str
    review_initiated_at_UTC: str
    resolved_by: Optional[str] = None
    resolved_at_UTC: Optional[str] = None
    modified_fields: Optional[ModifiedFieldsModel] = None
    dismissal_feedback: Optional[DismissalFeedbackModel] = None

    model_config = ConfigDict(use_enum_values=True)
