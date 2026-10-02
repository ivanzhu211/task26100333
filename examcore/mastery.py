"""知识点掌握状态机。"""

from __future__ import annotations

MASTER_THRESHOLD = 0.85
DEMOTE_THRESHOLD = 0.60
MASTER_STREAK = 3


def update_mastery(mastered: bool, streak: int, rate: float) -> tuple[bool, int]:
    """根据本次得分率推进掌握状态，返回 (是否已掌握, 连续高于阈值次数)。

    - 未掌握：连续 MASTER_STREAK 次严格高于 85% 进入已掌握；否则计数清零。
    - 已掌握：某次低于 60% 退回未掌握且计数清零；60%~85% 之间不改变状态。
    """
    if mastered:
        if rate < DEMOTE_THRESHOLD:
            return False, 0
        return True, streak
    if rate > MASTER_THRESHOLD:
        streak += 1
        if streak >= MASTER_STREAK:
            return True, streak
        return False, streak
    return False, 0
