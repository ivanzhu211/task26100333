"""验收场景：多名学员交卷 -> 题目修订版本 -> 勘误（换答案 / 作废）-> 继续交卷。

最终每个学员的答卷成绩、知识点掌握状态和复习计划，都必须与
按最终答案从头重算（本文件内的独立参照实现）的结果一致。
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from exam_learning import Errata, ExamLearningService

BASE = datetime(2026, 9, 1, 9, 0)


def at(days: int, hours: int = 0) -> datetime:
    return BASE + timedelta(days=days, hours=hours)


# ---------------------------------------------------------------------------
# 独立参照实现：给定最终勘误，从事件日志从头重算所有派生结果
# ---------------------------------------------------------------------------

def reference_recompute(versions, errata, papers, submissions):
    """versions: {vid: (qid, score, kps, answers)}
    errata: {vid: ("replace", answers) | ("void",)}
    papers: {pid: (pass_line, [qid, ...])}
    submissions: [(sid, student, pid, submitted_at, {qid: (vid, answer)})]
    返回 (results, mastery, plan)，结构与服务端查询结果对应。
    """
    intervals = {1: timedelta(days=1), 2: timedelta(days=3),
                 3: timedelta(days=7), 4: timedelta(days=14)}
    results = {}
    mastery = {}
    plan = {}
    for sid, student, pid, submitted_at, answers in submissions:
        pass_line, qids = papers[pid]
        per_question = {}
        score = total = 0
        for qid in qids:
            vid, answer = answers[qid]
            _, qscore, kps, qanswers = versions[vid]
            err = errata.get(vid)
            voided = err is not None and err[0] == "void"
            if voided:
                acceptable = ()
            elif err is not None:
                acceptable = err[1]
            else:
                acceptable = qanswers
            correct = (not voided) and answer in acceptable
            full = 0 if voided else qscore
            earned = qscore if correct else 0
            per_question[qid] = {
                "voided": voided, "correct": correct,
                "earned": earned, "full_score": full, "kps": kps,
            }
            score += earned
            total += full
        results[sid] = {
            "score": score, "total": total,
            "passed": total > 0 and score / total >= pass_line,
            "per_question": per_question,
        }
        # 知识点掌握
        by_kp = {}
        for qid in qids:
            qr = per_question[qid]
            if qr["voided"]:
                continue
            for kp in qr["kps"]:
                e, t = by_kp.get(kp, (0, 0))
                by_kp[kp] = (e + qr["earned"], t + qr["full_score"])
        for kp, (e, t) in by_kp.items():
            entry = mastery.setdefault(
                (student, kp), {"state": "unmastered", "streak": 0})
            if e * 100 > 85 * t:
                entry["streak"] += 1
                if entry["streak"] >= 3:
                    entry["state"] = "mastered"
            elif e * 100 < 60 * t:
                if entry["state"] == "mastered":
                    entry["state"] = "unmastered"
                entry["streak"] = 0
            else:
                entry["streak"] = 0
        # 复习计划
        for qid in qids:
            qr = per_question[qid]
            if qr["voided"]:
                continue
            key = (student, qid)
            if not qr["correct"]:
                plan[key] = {"stage": 1, "due": submitted_at + intervals[1]}
            elif key in plan and submitted_at >= plan[key]["due"]:
                if plan[key]["stage"] == 4:
                    del plan[key]
                else:
                    plan[key]["stage"] += 1
                    plan[key]["due"] = submitted_at + intervals[plan[key]["stage"]]
    return results, mastery, plan


# ---------------------------------------------------------------------------
# 验收场景
# ---------------------------------------------------------------------------

@pytest.fixture()
def scenario():
    svc = ExamLearningService()
    # Q1: K1, 10 分; Q2: K2, 10 分; Q3: K1+K2, 10 分
    q1 = svc.create_question(10, ["K1"], ["A"])
    q2 = svc.create_question(10, ["K2"], ["B"])
    q3 = svc.create_question(10, ["K1", "K2"], ["C"])
    paper = svc.create_paper([q1, q2, q3], 0.6)

    versions = {}
    errata = {}
    papers = {paper: (0.6, [q1, q2, q3])}
    submissions = []
    # 记录每份答卷每题实际使用的版本（参照重算需要）
    used_version = {}

    def submit(student, answers, when):
        sid = svc.submit(student, paper, answers, when)
        result = svc.get_submission_result(sid)
        recorded = {
            qr.question_id: (qr.version_id, answers.get(qr.question_id, ""))
            for qr in result.question_results
        }
        submissions.append((sid, student, paper, when, recorded))
        return sid

    # 阶段一：勘误前的交卷（全部使用 v1）
    s1_d0 = submit("s1", {q1: "A", q2: "B", q3: "C"}, at(0))
    s2_d1 = submit("s2", {q1: "A", q2: "X", q3: "C"}, at(1))
    s3_d1 = submit("s3", {q1: "A", q2: "B", q3: "C"}, at(1, 6))

    # 题目修订：Q2 出新版本（不算勘误，不影响旧答卷）
    q2_v2 = svc.revise_question(q2, 10, ["K2"], ["D"])

    s1_d2 = submit("s1", {q1: "A", q2: "D", q3: "C"}, at(2))
    s3_d2 = submit("s3", {q1: "A", q2: "D", q3: "C"}, at(2, 6))

    # 阶段二：勘误。Q1 v1 换答案（A 不再可接受），Q3 v1 作废
    q1_v1 = svc.get_submission_result(s1_d0).question_results[0].version_id
    q3_v1 = [qr for qr in svc.get_submission_result(s1_d0).question_results
             if qr.question_id == q3][0].version_id
    svc.apply_errata(q1_v1, Errata.replace_answers(["A2"]))
    svc.apply_errata(q3_v1, Errata.void())
    errata[q1_v1] = ("replace", ("A2",))
    errata[q3_v1] = ("void",)

    # 阶段三：勘误后的交卷
    s1_d3 = submit("s1", {q1: "A2", q2: "D", q3: "C"}, at(3))
    s2_d4 = submit("s2", {q1: "A2", q2: "D", q3: "C"}, at(4))
    s2_d5 = submit("s2", {q1: "A2", q2: "D", q3: "C"}, at(5))   # 未到期答对，不升档
    s2_d8 = submit("s2", {q1: "A2", q2: "D", q3: "C"}, at(8))   # 到期升第 3 档
    s3_d9 = submit("s3", {q1: "A", q2: "X", q3: "C"}, at(9))    # 两题答错
    s2_d16 = submit("s2", {q1: "A2", q2: "D", q3: "C"}, at(16))  # 升第 4 档
    s2_d31 = submit("s2", {q1: "A2", q2: "D", q3: "C"}, at(31))  # 第 4 档到期答对，移出

    # 参照重算需要的版本表
    for sid, student, pid, when, recorded in submissions:
        for qid, (vid, _ans) in recorded.items():
            if vid in versions:
                continue
    versions[q1_v1] = (q1, 10, ("K1",), ("A",))
    versions[q3_v1] = (q3, 10, ("K1", "K2"), ("C",))
    # Q2 的 v1 / v2
    q2_v1 = [qr for qr in svc.get_submission_result(s2_d1).question_results
             if qr.question_id == q2][0].version_id
    versions[q2_v1] = (q2, 10, ("K2",), ("B",))
    versions[q2_v2] = (q2, 10, ("K2",), ("D",))

    return {
        "svc": svc, "q1": q1, "q2": q2, "q3": q3, "paper": paper,
        "versions": versions, "errata": errata, "papers": papers,
        "submissions": submissions,
        "ids": {"s1_d0": s1_d0, "s2_d1": s2_d1, "s1_d2": s1_d2},
    }


def test_errata_corrects_history(scenario):
    """勘误后，历史答卷成绩立即被纠正。"""
    svc = scenario["svc"]
    ids = scenario["ids"]
    # s1 第一天：Q1 的 A 不再可接受（错），Q3 作废 -> 只有 Q2 计分，10/20
    r = svc.get_submission_result(ids["s1_d0"])
    assert (r.score, r.total, r.passed) == (10, 20, False)
    qr = {x.question_id: x for x in r.question_results}
    assert qr[scenario["q3"]].voided
    assert not qr[scenario["q1"]].correct
    # s2 第一天：Q1 错、Q2 错、Q3 作废 -> 0/20
    r2 = svc.get_submission_result(ids["s2_d1"])
    assert (r2.score, r2.total, r2.passed) == (0, 20, False)
    # s1 第二天用的是 Q2 新版本，不受 Q2 旧版本影响；Q1 错 -> 10/20
    r3 = svc.get_submission_result(ids["s1_d2"])
    assert (r3.score, r3.total, r3.passed) == (10, 20, False)


def test_final_state_matches_full_recompute(scenario):
    """最终状态与按最终答案从头重算的结果完全一致。"""
    svc = scenario["svc"]
    results, mastery, plan = reference_recompute(
        scenario["versions"], scenario["errata"],
        scenario["papers"], scenario["submissions"],
    )
    students = {"s1", "s2", "s3"}

    # 1. 每份答卷成绩
    for sid, expected in results.items():
        actual = svc.get_submission_result(sid)
        assert (actual.score, actual.total, actual.passed) == (
            expected["score"], expected["total"], expected["passed"]), sid
        for qr in actual.question_results:
            eq = expected["per_question"][qr.question_id]
            assert (qr.voided, qr.correct, qr.earned, qr.full_score) == (
                eq["voided"], eq["correct"], eq["earned"], eq["full_score"]), sid

    # 2. 每个学员的知识点掌握状态
    for student in students:
        actual = {
            m.knowledge_point: (m.state.value, m.consecutive_high)
            for m in svc.get_mastery(student)
        }
        expected = {
            kp: (v["state"], v["streak"])
            for (s, kp), v in mastery.items() if s == student
        }
        assert actual == expected, student

    # 3. 每个学员的复习计划
    for student in students:
        actual = {
            item.question_id: (item.stage, item.due_at)
            for item in svc.get_review_plan(student)
        }
        expected = {
            qid: (v["stage"], v["due"])
            for (s, qid), v in plan.items() if s == student
        }
        assert actual == expected, student

    # 场景应确实覆盖到关键路径，防止参照实现空转
    assert any(m["state"] == "mastered" for m in mastery.values())
    assert any(v["stage"] >= 2 for v in plan.values()) or not plan
    assert any(r["passed"] for r in results.values())
