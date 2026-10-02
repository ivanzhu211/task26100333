"""复习计划（按学员 + 题目的间隔重复，不分题目版本）。"""

from __future__ import annotations

from datetime import datetime, timedelta

from examcore.models import ReviewItem

TIER_INTERVALS = {
    1: timedelta(days=1),
    2: timedelta(days=3),
    3: timedelta(days=7),
    4: timedelta(days=14),
}
MAX_TIER = 4


def update_review(
    item: ReviewItem | None,
    question_id: int,
    correct: bool,
    submitted_at: datetime,
) -> ReviewItem | None:
    """根据本次作答更新某题的复习计划条目，返回新条目；None 表示移出计划。

    - 答错：进入或重置到第 1 档，到期时间为交卷时间 +1 天。
    - 计划内的题到期后答对：升一档，到期时间依次为 +3/+7/+14 天；
      第 4 档到期后再答对则移出计划。
    - 没到期就答对：不升档，条目不变。
    """
    if not correct:
        return ReviewItem(
            question_id=question_id,
            tier=1,
            due_at=submitted_at + TIER_INTERVALS[1],
        )
    if item is None or submitted_at < item.due_at:
        return item
    if item.tier >= MAX_TIER:
        return None
    new_tier = item.tier + 1
    return ReviewItem(
        question_id=question_id,
        tier=new_tier,
        due_at=submitted_at + TIER_INTERVALS[new_tier],
    )
