"""判分、掌握状态机、复习计划的单元测试。"""

from datetime import datetime, timedelta

import pytest

from examcore.grading import grade_answers, summarize
from examcore.mastery import update_mastery
from examcore.review import update_review

T0 = datetime(2026, 1, 1, 9, 0, 0)


# ---- 判分 ----

def _grade(answers, effective, points=5):
    return grade_answers(
        [1], {1: 1}, {1: answers}, {1: (points, ["kp"])}, {(1, 1): effective}
    )[0]


def test_exact_match_only():
    assert _grade("A", ["A"]).correct
    assert not _grade("a", ["A"]).correct  # 大小写不同
    assert not _grade("A ", ["A"]).correct  # 多空格
    assert not _grade("", ["A"]).correct
    assert _grade("x", ["A", "x"]).correct  # 任一可接受答案即可


def test_voided_excluded_from_total():
    results = grade_answers(
        [1, 2],
        {1: 1, 2: 1},
        {1: "A", 2: "B"},
        {1: (5, ["k"]), 2: (10, ["k"])},
        {(1, 1): ["A"], (2, 1): None},
    )
    score, total, rate, passed = summarize(results, 0.5)
    assert (score, total, rate, passed) == (5, 5, 1.0, True)


def test_all_voided_rate_is_zero():
    results = grade_answers([1], {1: 1}, {1: "A"}, {1: (5, ["k"])}, {(1, 1): None})
    assert summarize(results, 0.0) == (0, 0, 0.0, True)
    assert summarize(results, 0.5)[3] is False


def test_pass_line_boundary():
    results = grade_answers([1], {1: 1}, {1: "A"}, {1: (5, ["k"])}, {(1, 1): ["A"]})
    assert summarize(results, 1.0)[3] is True  # 达到及格线即通过


# ---- 知识点掌握 ----

def test_mastery_three_consecutive_above_85():
    state = (False, 0)
    state = update_mastery(*state, 0.9)
    assert state == (False, 1)
    state = update_mastery(*state, 1.0)
    assert state == (False, 2)
    state = update_mastery(*state, 0.86)
    assert state == (True, 3)


def test_mastery_exactly_85_does_not_count():
    assert update_mastery(False, 2, 0.85) == (False, 0)


def test_mastery_streak_resets_on_low_score():
    assert update_mastery(False, 2, 0.4) == (False, 0)


def test_mastery_demote_below_60_and_reset():
    assert update_mastery(True, 5, 0.59) == (False, 0)
    assert update_mastery(True, 5, 0.0) == (False, 0)


def test_mastery_holds_between_60_and_85():
    assert update_mastery(True, 5, 0.6) == (True, 5)  # 恰好 60% 不退回
    assert update_mastery(True, 5, 0.85) == (True, 5)
    assert update_mastery(True, 5, 0.7) == (True, 5)


# ---- 复习计划 ----

def test_wrong_enters_tier1():
    item = update_review(None, 1, False, T0)
    assert (item.tier, item.due_at) == (1, T0 + timedelta(days=1))


def test_correct_before_due_does_not_promote():
    item = update_review(None, 1, False, T0)
    assert update_review(item, 1, True, item.due_at - timedelta(seconds=1)) is item


def test_correct_at_due_promotes():
    item = update_review(None, 1, False, T0)
    promoted = update_review(item, 1, True, item.due_at)
    assert (promoted.tier, promoted.due_at) == (2, item.due_at + timedelta(days=3))


def test_tier_intervals_and_graduation():
    item = update_review(None, 1, False, T0)
    item = update_review(item, 1, True, item.due_at)  # -> 2 档，+3 天
    assert item.tier == 2
    item = update_review(item, 1, True, item.due_at)  # -> 3 档，+7 天
    assert item.tier == 3
    item = update_review(item, 1, True, item.due_at)  # -> 4 档，+14 天
    assert item.tier == 4
    assert update_review(item, 1, True, item.due_at) is None  # 移出计划


def test_wrong_resets_to_tier1():
    item = update_review(None, 1, False, T0)
    item = update_review(item, 1, True, item.due_at)
    t = item.due_at + timedelta(days=5)
    reset = update_review(item, 1, False, t)
    assert (reset.tier, reset.due_at) == (1, t + timedelta(days=1))


def test_correct_not_in_plan_is_noop():
    assert update_review(None, 1, True, T0) is None
