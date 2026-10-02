"""业务规则单元测试：掌握状态机、复习计划状态机、作废与版本隔离。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from exam_learning import Errata, ExamLearningService, MasteryState

BASE = datetime(2026, 9, 1, 9, 0)


def at(days: int) -> datetime:
    return BASE + timedelta(days=days)


def make_kp_paper(svc, kp, n, score=10, pass_line=0.6):
    """造一张含 n 道同一知识点题目的试卷，返回 (paper_id, [qid, ...])。
    每题可接受答案为 "ok{i}"。"""
    qids = [
        svc.create_question(score, [kp], [f"ok{i}"]) for i in range(n)
    ]
    return svc.create_paper(qids, pass_line), qids


def answers_for(qids, correct_count):
    return {
        qid: (f"ok{i}" if i < correct_count else "bad")
        for i, qid in enumerate(qids)
    }


# ---------------------------------------------------------------------------
# 知识点掌握
# ---------------------------------------------------------------------------

def test_mastery_three_consecutive_above_85():
    svc = ExamLearningService()
    paper, qids = make_kp_paper(svc, "K", 20)
    for day in (0, 1, 2):
        svc.submit("s", paper, answers_for(qids, 18), at(day))  # 90%
    m = svc.get_mastery("s")[0]
    assert m.state == MasteryState.MASTERED
    assert m.consecutive_high == 3


def test_mastery_exactly_85_does_not_count():
    svc = ExamLearningService()
    paper, qids = make_kp_paper(svc, "K", 20)
    for day in (0, 1, 2):
        svc.submit("s", paper, answers_for(qids, 17), at(day))  # 恰好 85%
    m = svc.get_mastery("s")[0]
    assert m.state == MasteryState.UNMASTERED
    assert m.consecutive_high == 0


def test_mastery_streak_broken_by_mid_range():
    svc = ExamLearningService()
    paper, qids = make_kp_paper(svc, "K", 20)
    svc.submit("s", paper, answers_for(qids, 18), at(0))   # 90%, streak=1
    svc.submit("s", paper, answers_for(qids, 14), at(1))   # 70%, streak 清零
    svc.submit("s", paper, answers_for(qids, 18), at(2))   # streak=1
    svc.submit("s", paper, answers_for(qids, 18), at(3))   # streak=2
    m = svc.get_mastery("s")[0]
    assert m.state == MasteryState.UNMASTERED
    assert m.consecutive_high == 2


def test_mastery_drop_below_60_and_mid_range_keeps_state():
    svc = ExamLearningService()
    paper, qids = make_kp_paper(svc, "K", 20)
    for day in (0, 1, 2):
        svc.submit("s", paper, answers_for(qids, 20), at(day))  # 已掌握
    svc.submit("s", paper, answers_for(qids, 14), at(3))  # 70%: 不改变已掌握
    assert svc.get_mastery("s")[0].state == MasteryState.MASTERED
    svc.submit("s", paper, answers_for(qids, 11), at(4))  # 55% < 60%: 退回
    m = svc.get_mastery("s")[0]
    assert m.state == MasteryState.UNMASTERED
    assert m.consecutive_high == 0


# ---------------------------------------------------------------------------
# 复习计划
# ---------------------------------------------------------------------------

def test_review_plan_stages_and_removal():
    svc = ExamLearningService()
    paper, qids = make_kp_paper(svc, "K", 1)
    q = qids[0]
    svc.submit("s", paper, {q: "bad"}, at(0))            # 答错 -> 第 1 档, due=day1
    (item,) = svc.get_review_plan("s")
    assert (item.stage, item.due_at) == (1, at(1))

    svc.submit("s", paper, {q: "ok0"}, at(1))            # 到期答对 -> 第 2 档
    (item,) = svc.get_review_plan("s")
    assert (item.stage, item.due_at) == (2, at(4))

    svc.submit("s", paper, {q: "ok0"}, at(2))            # 未到期答对 -> 不升档
    (item,) = svc.get_review_plan("s")
    assert (item.stage, item.due_at) == (2, at(4))

    svc.submit("s", paper, {q: "ok0"}, at(4))            # -> 第 3 档
    (item,) = svc.get_review_plan("s")
    assert (item.stage, item.due_at) == (3, at(11))

    svc.submit("s", paper, {q: "ok0"}, at(11))           # -> 第 4 档
    (item,) = svc.get_review_plan("s")
    assert (item.stage, item.due_at) == (4, at(25))

    svc.submit("s", paper, {q: "ok0"}, at(25))           # 第 4 档到期答对 -> 移出
    assert svc.get_review_plan("s") == []


def test_review_plan_wrong_resets_to_stage1():
    svc = ExamLearningService()
    paper, qids = make_kp_paper(svc, "K", 1)
    q = qids[0]
    svc.submit("s", paper, {q: "bad"}, at(0))
    svc.submit("s", paper, {q: "ok0"}, at(1))            # 第 2 档
    svc.submit("s", paper, {q: "bad"}, at(2))            # 答错 -> 重置第 1 档
    (item,) = svc.get_review_plan("s")
    assert (item.stage, item.due_at) == (1, at(3))


def test_review_plan_correct_not_in_plan_is_noop():
    svc = ExamLearningService()
    paper, qids = make_kp_paper(svc, "K", 1)
    svc.submit("s", paper, {qids[0]: "ok0"}, at(0))
    assert svc.get_review_plan("s") == []


# ---------------------------------------------------------------------------
# 作废与版本
# ---------------------------------------------------------------------------

def test_void_excludes_from_score_mastery_and_plan():
    svc = ExamLearningService()
    q1 = svc.create_question(10, ["K"], ["A"])
    q2 = svc.create_question(10, ["K"], ["B"])
    paper = svc.create_paper([q1, q2], 0.6)
    sid = svc.submit("s", paper, {q1: "A", q2: "bad"}, at(0))
    assert svc.get_review_plan("s")[0].question_id == q2

    q2_v1 = svc.get_submission_result(sid).question_results[1].version_id
    svc.apply_errata(q2_v1, Errata.void())

    r = svc.get_submission_result(sid)
    assert (r.score, r.total, r.passed) == (10, 10, True)
    assert svc.get_review_plan("s") == []                # 当作没答过
    m = svc.get_mastery("s")[0]                          # 掌握率只看未作废题
    assert (m.state, m.consecutive_high) == (MasteryState.UNMASTERED, 1)


def test_errata_only_affects_the_target_version():
    svc = ExamLearningService()
    q = svc.create_question(10, ["K"], ["A"])
    paper = svc.create_paper([q], 0.6)
    old_sub = svc.submit("s", paper, {q: "A"}, at(0))    # 用 v1
    v2 = svc.revise_question(q, 10, ["K"], ["B"])
    new_sub = svc.submit("s", paper, {q: "B"}, at(1))    # 用 v2

    old_v1 = svc.get_submission_result(old_sub).question_results[0].version_id
    svc.apply_errata(old_v1, Errata.replace_answers(["C"]))

    assert svc.get_submission_result(old_sub).score == 0   # 旧版被纠正
    assert svc.get_submission_result(new_sub).score == 10  # 新版不受影响


def test_revision_alone_does_not_change_old_results():
    svc = ExamLearningService()
    q = svc.create_question(10, ["K"], ["A"])
    paper = svc.create_paper([q], 0.6)
    old_sub = svc.submit("s", paper, {q: "A"}, at(0))
    svc.revise_question(q, 10, ["K"], ["B"])             # 仅修订，不算勘误
    assert svc.get_submission_result(old_sub).score == 10


def test_multiple_acceptable_answers_exact_match():
    svc = ExamLearningService()
    q = svc.create_question(10, ["K"], ["A", "a", "甲"])
    paper = svc.create_paper([q], 0.6)
    for i, ans in enumerate(["A", "a", "甲"]):
        sid = svc.submit(f"s{i}", paper, {q: ans}, at(i))
        assert svc.get_submission_result(sid).score == 10
    sid = svc.submit("sx", paper, {q: "A "}, at(4))      # 逐字相同才算对
    assert svc.get_submission_result(sid).score == 0
