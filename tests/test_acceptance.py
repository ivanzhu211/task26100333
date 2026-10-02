"""验收场景：多名学员先后交卷，题目修订版本，随后勘误（旧版本换答案、
另一道题作废），再继续交卷。最终所有答卷成绩、知识点掌握状态、复习计划
必须与按最终答案从头重算的结果一致。"""

from datetime import datetime, timedelta

import pytest

from examcore import GradingService

BASE = datetime(2026, 3, 1, 9, 0, 0)
DAY = timedelta(days=1)

# 题目元数据：qid -> (分值, 知识点)
QUESTIONS = {
    1: (5, ["algebra"]),
    2: (5, ["algebra"]),
    3: (10, ["geometry"]),
    4: (10, ["geometry"]),
}
# 试卷：pid -> (题目列表, 及格线)
PAPERS = {
    1: ([1, 2, 3], 0.6),
    2: ([1, 3, 4], 0.6),
}
# 最终生效答案：(qid, version) -> 可接受答案，None 表示作废
FINAL_ANSWERS = {
    (1, 1): ["A", "B"],  # 勘误：旧版本换答案
    (1, 2): ["A", "A2"],  # 修订产生的新版本，不受勘误影响
    (2, 1): ["X"],
    (3, 1): None,  # 勘误：作废
    (4, 1): ["m"],
}


def reference_recompute(submissions):
    """独立参照实现：按交卷时间，用最终答案从头重算每个学员的全部状态。"""
    results = {}
    mastery_by_student = {}
    review_by_student = {}
    by_student: dict[str, list[dict]] = {}
    for sub in submissions:
        by_student.setdefault(sub["student"], []).append(sub)

    for student, subs in by_student.items():
        subs.sort(key=lambda s: (s["time"], s["id"]))
        mastery: dict[str, list] = {}  # kp -> [mastered, streak]
        review: dict[int, list] = {}  # qid -> [tier, due]
        for sub in subs:
            qids, pass_line = PAPERS[sub["paper"]]
            score = total = 0
            details = {}
            kp_earned: dict[str, int] = {}
            kp_total: dict[str, int] = {}
            for qid in qids:
                points, kps = QUESTIONS[qid]
                effective = FINAL_ANSWERS[(qid, sub["versions"][qid])]
                if effective is None:
                    details[qid] = {"voided": True, "correct": False, "earned": 0}
                    continue
                correct = sub["answers"].get(qid) in effective
                earned = points if correct else 0
                details[qid] = {"voided": False, "correct": correct, "earned": earned}
                score += earned
                total += points
                for kp in kps:
                    kp_earned[kp] = kp_earned.get(kp, 0) + earned
                    kp_total[kp] = kp_total.get(kp, 0) + points
                if not correct:
                    review[qid] = [1, sub["time"] + timedelta(days=1)]
                elif qid in review and sub["time"] >= review[qid][1]:
                    tier = review[qid][0]
                    if tier >= 4:
                        del review[qid]
                    else:
                        interval = {2: 3, 3: 7, 4: 14}[tier + 1]
                        review[qid] = [tier + 1, sub["time"] + timedelta(days=interval)]
            for kp, kp_tot in kp_total.items():
                rate = kp_earned[kp] / kp_tot
                mastered, streak = mastery.get(kp, [False, 0])
                if mastered:
                    if rate < 0.60:
                        mastered, streak = False, 0
                elif rate > 0.85:
                    streak += 1
                    if streak >= 3:
                        mastered = True
                else:
                    streak = 0
                mastery[kp] = [mastered, streak]
            rate = score / total if total else 0.0
            results[sub["id"]] = {
                "score": score,
                "total": total,
                "rate": rate,
                "passed": rate >= pass_line,
                "details": details,
            }
        mastery_by_student[student] = mastery
        review_by_student[student] = review
    return results, mastery_by_student, review_by_student


@pytest.fixture()
def scenario():
    """构建完整场景，返回 (service, submissions, 各阶段快照)。"""
    svc = GradingService()
    q1 = svc.create_question(5, ["algebra"], ["A"])
    q2 = svc.create_question(5, ["algebra"], ["X"])
    q3 = svc.create_question(10, ["geometry"], ["g1"])
    q4 = svc.create_question(10, ["geometry"], ["m"])
    assert (q1, q2, q3, q4) == (1, 2, 3, 4)
    p1 = svc.create_paper([q1, q2, q3], 0.6)
    p2 = svc.create_paper([q1, q3, q4], 0.6)
    assert (p1, p2) == (1, 2)

    versions = {q1: 1, q2: 1, q3: 1, q4: 1}
    submissions = []

    def submit(student, paper, answers, day):
        recorded = {qid: versions[qid] for qid in PAPERS[paper][0]}
        sid = svc.submit(student, paper, answers, BASE + day * DAY)
        submissions.append(
            {
                "id": sid,
                "student": student,
                "paper": paper,
                "answers": answers,
                "versions": recorded,
                "time": BASE + day * DAY,
            }
        )
        return sid

    # 勘误前的答卷
    s1 = submit("alice", p1, {q1: "A", q2: "Y", q3: "g1"}, 1)
    s2 = submit("bob", p1, {q1: "B", q2: "X", q3: "bad"}, 2)

    # 题目修订出新版本（不算勘误，不影响旧答卷）
    assert svc.revise_question(q1, ["A", "A2"]) == 2
    versions[q1] = 2
    snapshot_after_revision = svc.get_submission_result(s1)

    s3 = submit("alice", p2, {q1: "A2", q3: "g1", q4: "m"}, 4)
    s4 = submit("carol", p1, {q1: "A2", q2: "X", q3: "zzz"}, 5)
    s5 = submit("carol", p2, {q1: "A2", q3: "g1", q4: "m"}, 6)
    s6 = submit("carol", p2, {q1: "A2", q3: "g1", q4: "m"}, 7)

    # 勘误：q1 旧版本换答案；q3 作废
    svc.issue_erratum(q1, 1, new_answers=["A", "B"])
    svc.issue_erratum(q3, 1, void=True)

    # 勘误后的答卷
    s7 = submit("alice", p1, {q1: "A", q2: "Y", q3: "g1"}, 8)
    s8 = submit("bob", p2, {q1: "nope", q3: "g1", q4: "m"}, 9)
    s9 = submit("alice", p2, {q1: "A2", q3: "g1", q4: "wrong"}, 10)
    s10 = submit("bob", p2, {q1: "A2", q3: "g1", q4: "m"}, 11)

    return svc, submissions, snapshot_after_revision, s1


def test_revision_does_not_change_history(scenario):
    """题目修订不算勘误：修订后旧答卷成绩不变。"""
    _svc, _subs, snapshot, _s1 = scenario
    # q1v1 'A'✓5, q2v1 'Y'✗0, q3v1 'g1'✓10 -> 15/20
    assert (snapshot.score, snapshot.total, snapshot.passed) == (15, 20, True)


def test_final_state_matches_full_recompute(scenario):
    svc, submissions, _snapshot, _s1 = scenario
    exp_results, exp_mastery, exp_review = reference_recompute(submissions)

    # 1) 每份答卷成绩
    for sub in submissions:
        actual = svc.get_submission_result(sub["id"])
        expected = exp_results[sub["id"]]
        assert actual.score == expected["score"], sub
        assert actual.total == expected["total"], sub
        assert actual.rate == pytest.approx(expected["rate"]), sub
        assert actual.passed == expected["passed"], sub
        for detail in actual.details:
            exp_d = expected["details"][detail.question_id]
            assert detail.voided == exp_d["voided"], (sub, detail)
            assert detail.correct == exp_d["correct"], (sub, detail)
            assert detail.earned == exp_d["earned"], (sub, detail)

    # 2) 每个学员的知识点掌握状态
    for student in ("alice", "bob", "carol"):
        actual_mastery = {
            m.knowledge_point: (m.mastered, m.streak) for m in svc.get_mastery(student)
        }
        expected_mastery = {
            kp: (v[0], v[1]) for kp, v in exp_mastery[student].items()
        }
        assert actual_mastery == expected_mastery, student

    # 3) 每个学员的复习计划
    for student in ("alice", "bob", "carol"):
        actual_review = {
            item.question_id: (item.tier, item.due_at)
            for item in svc.get_review_plan(student)
        }
        expected_review = {
            qid: (v[0], v[1]) for qid, v in exp_review[student].items()
        }
        assert actual_review == expected_review, student


def test_erratum_effects_are_concrete(scenario):
    """对关键结果做硬编码断言，防止参照实现与实现犯同样的错。"""
    svc, submissions, _snapshot, s1 = scenario
    by_id = {s["id"]: s for s in submissions}

    # alice 第一次：q1v1✓5，q2 'Y'✗0，q3 作废 -> 5/10 不及格
    r1 = svc.get_submission_result(s1)
    assert (r1.score, r1.total, r1.passed) == (5, 10, False)

    # bob 第一次：q1v1 'B' 因勘误改对，q2✓，q3 作废 -> 10/10
    r2 = svc.get_submission_result(by_id[2]["id"])
    assert (r2.score, r2.total, r2.passed) == (10, 10, True)

    # carol 连续三次 algebra 满分 -> 已掌握
    carol_mastery = {m.knowledge_point: m for m in svc.get_mastery("carol")}
    assert carol_mastery["algebra"].mastered is True
    assert carol_mastery["algebra"].streak == 3

    # alice：q2 两次答错重置到 1 档（第 8 天 +1），q4 第 10 天答错入 1 档
    alice_review = {i.question_id: i for i in svc.get_review_plan("alice")}
    assert (alice_review[2].tier, alice_review[2].due_at) == (1, BASE + 9 * DAY)
    assert (alice_review[4].tier, alice_review[4].due_at) == (1, BASE + 11 * DAY)

    # bob：q1 第 9 天答错入 1 档，第 11 天到期后答对升 2 档（+3 天）
    bob_review = {i.question_id: i for i in svc.get_review_plan("bob")}
    assert (bob_review[1].tier, bob_review[1].due_at) == (2, BASE + 14 * DAY)

    # carol 全部答对（q3 作废视为没答过）-> 复习计划为空
    assert svc.get_review_plan("carol") == []


def test_empty_state_for_unknown_student(scenario):
    svc, _subs, _snapshot, _s1 = scenario
    assert svc.get_mastery("nobody") == []
    assert svc.get_review_plan("nobody") == []
