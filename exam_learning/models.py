"""领域模型与类型定义。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ErrataType(str, Enum):
    REPLACE_ANSWERS = "replace_answers"
    VOID = "void"


@dataclass(frozen=True)
class Errata:
    """针对题目某一版本的勘误。"""
    errata_type: ErrataType
    new_answers: tuple[str, ...] = ()

    @staticmethod
    def replace_answers(new_answers: list[str]) -> "Errata":
        return Errata(ErrataType.REPLACE_ANSWERS, tuple(new_answers))

    @staticmethod
    def void() -> "Errata":
        return Errata(ErrataType.VOID)


@dataclass(frozen=True)
class QuestionVersion:
    version_id: int
    question_id: int
    version_no: int
    score: int
    knowledge_points: tuple[str, ...]
    acceptable_answers: tuple[str, ...]


@dataclass(frozen=True)
class QuestionResult:
    """答卷中单题的判分结果。"""
    question_id: int
    version_id: int
    answer: str
    voided: bool
    correct: bool
    earned: int
    full_score: int


@dataclass(frozen=True)
class SubmissionResult:
    submission_id: int
    student_id: str
    paper_id: int
    submitted_at: datetime
    score: int
    total: int
    passed: bool
    question_results: tuple[QuestionResult, ...] = ()

    @property
    def rate(self) -> float:
        return self.score / self.total if self.total > 0 else 0.0


class MasteryState(str, Enum):
    MASTERED = "mastered"
    UNMASTERED = "unmastered"


@dataclass(frozen=True)
class MasteryStatus:
    student_id: str
    knowledge_point: str
    state: MasteryState
    consecutive_high: int


@dataclass(frozen=True)
class ReviewItem:
    student_id: str
    question_id: int
    stage: int
    due_at: datetime
