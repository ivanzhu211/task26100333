"""领域模型：纯数据定义，不含持久化逻辑。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class QuestionResult:
    """一份答卷中某道题的判分结果。"""

    question_id: int
    version_no: int
    voided: bool
    correct: bool
    earned: int
    points: int


@dataclass(frozen=True)
class SubmissionResult:
    """一份答卷的整体判分结果。"""

    submission_id: int
    student_id: str
    paper_id: int
    submitted_at: datetime
    score: int
    total: int
    rate: float
    passed: bool
    details: tuple[QuestionResult, ...]


@dataclass(frozen=True)
class MasteryState:
    """某学员在某知识点上的掌握状态。"""

    knowledge_point: str
    mastered: bool
    streak: int


@dataclass(frozen=True)
class ReviewItem:
    """复习计划条目（按学员 + 题目，不分版本）。"""

    question_id: int
    tier: int
    due_at: datetime
