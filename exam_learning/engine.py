"""判分与学情重算引擎：按交卷时间重放全部答卷，重建派生数据。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

# 复习计划各档位的间隔：1/3/7/14 天
STAGE_INTERVALS = {1: timedelta(days=1), 2: timedelta(days=3),
                   3: timedelta(days=7), 4: timedelta(days=14)}
MAX_STAGE = 4


def _load_errata(conn: sqlite3.Connection) -> dict[int, tuple[str, tuple[str, ...]]]:
    rows = conn.execute(
        "SELECT version_id, errata_type, new_answers FROM errata"
    ).fetchall()
    result: dict[int, tuple[str, tuple[str, ...]]] = {}
    for row in rows:
        new_answers = tuple(json.loads(row["new_answers"])) if row["new_answers"] else ()
        result[row["version_id"]] = (row["errata_type"], new_answers)
    return result


def _load_versions(conn: sqlite3.Connection) -> dict[int, dict]:
    rows = conn.execute(
        "SELECT version_id, question_id, score, knowledge_points, acceptable_answers"
        " FROM question_versions"
    ).fetchall()
    return {
        row["version_id"]: {
            "question_id": row["question_id"],
            "score": row["score"],
            "knowledge_points": tuple(json.loads(row["knowledge_points"])),
            "acceptable_answers": tuple(json.loads(row["acceptable_answers"])),
        }
        for row in rows
    }


def _grade_submission(
    conn: sqlite3.Connection,
    submission_id: int,
    errata_map: dict[int, tuple[str, tuple[str, ...]]],
    versions: dict[int, dict],
) -> list[dict]:
    """判一份答卷，返回逐题结果列表。"""
    answers = conn.execute(
        "SELECT question_id, version_id, answer FROM submission_answers"
        " WHERE submission_id = ? ORDER BY question_id",
        (submission_id,),
    ).fetchall()
    results = []
    for row in answers:
        version = versions[row["version_id"]]
        errata = errata_map.get(row["version_id"])
        voided = errata is not None and errata[0] == "void"
        if voided:
            acceptable: tuple[str, ...] = ()
        elif errata is not None:
            acceptable = errata[1]
        else:
            acceptable = version["acceptable_answers"]
        correct = (not voided) and row["answer"] in acceptable
        full_score = 0 if voided else version["score"]
        results.append({
            "question_id": row["question_id"],
            "version_id": row["version_id"],
            "answer": row["answer"],
            "voided": voided,
            "correct": correct,
            "earned": version["score"] if correct else 0,
            "full_score": full_score,
            "knowledge_points": version["knowledge_points"],
        })
    return results


def _update_mastery(
    mastery: dict[tuple[str, str], dict],
    student_id: str,
    question_results: list[dict],
) -> None:
    """按一份答卷的逐题结果推进知识点掌握状态机。"""
    by_kp: dict[str, tuple[int, int]] = {}
    for qr in question_results:
        if qr["voided"]:
            continue
        for kp in qr["knowledge_points"]:
            earned, total = by_kp.get(kp, (0, 0))
            by_kp[kp] = (earned + qr["earned"], total + qr["full_score"])
    for kp, (earned, total) in by_kp.items():
        key = (student_id, kp)
        entry = mastery.setdefault(
            key, {"state": "unmastered", "consecutive_high": 0}
        )
        # 用整数交叉相乘比较，避免浮点误差：高于 85% / 低于 60%
        if earned * 100 > 85 * total:
            entry["consecutive_high"] += 1
            if entry["consecutive_high"] >= 3:
                entry["state"] = "mastered"
        elif earned * 100 < 60 * total:
            if entry["state"] == "mastered":
                entry["state"] = "unmastered"
            entry["consecutive_high"] = 0
        else:
            entry["consecutive_high"] = 0


def _update_review_plan(
    plan: dict[tuple[str, int], dict],
    student_id: str,
    submitted_at: datetime,
    question_results: list[dict],
) -> None:
    """按一份答卷的逐题结果推进复习计划状态机。"""
    for qr in question_results:
        if qr["voided"]:
            continue
        key = (student_id, qr["question_id"])
        if not qr["correct"]:
            plan[key] = {"stage": 1, "due_at": submitted_at + STAGE_INTERVALS[1]}
            continue
        item = plan.get(key)
        if item is None or submitted_at < item["due_at"]:
            continue
        if item["stage"] >= MAX_STAGE:
            del plan[key]
        else:
            item["stage"] += 1
            item["due_at"] = submitted_at + STAGE_INTERVALS[item["stage"]]


def rebuild_all(conn: sqlite3.Connection) -> None:
    """重放所有答卷，重建成绩、知识点掌握与复习计划。"""
    errata_map = _load_errata(conn)
    versions = _load_versions(conn)
    papers = {
        row["paper_id"]: row["pass_line"]
        for row in conn.execute("SELECT paper_id, pass_line FROM papers").fetchall()
    }
    submissions = conn.execute(
        "SELECT submission_id, student_id, paper_id, submitted_at"
        " FROM submissions ORDER BY submitted_at, submission_id"
    ).fetchall()

    mastery: dict[tuple[str, str], dict] = {}
    plan: dict[tuple[str, int], dict] = {}

    with conn:
        conn.execute("DELETE FROM submission_results")
        conn.execute("DELETE FROM question_results")
        conn.execute("DELETE FROM mastery")
        conn.execute("DELETE FROM review_plan")

        for sub in submissions:
            submitted_at = datetime.fromisoformat(sub["submitted_at"])
            results = _grade_submission(
                conn, sub["submission_id"], errata_map, versions
            )
            score = sum(r["earned"] for r in results)
            total = sum(r["full_score"] for r in results)
            pass_line = papers[sub["paper_id"]]
            passed = total > 0 and score >= pass_line * total

            conn.execute(
                "INSERT INTO submission_results (submission_id, score, total, passed)"
                " VALUES (?, ?, ?, ?)",
                (sub["submission_id"], score, total, int(passed)),
            )
            for r in results:
                conn.execute(
                    "INSERT INTO question_results (submission_id, question_id,"
                    " version_id, answer, voided, correct, earned, full_score)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (sub["submission_id"], r["question_id"], r["version_id"],
                     r["answer"], int(r["voided"]), int(r["correct"]),
                     r["earned"], r["full_score"]),
                )

            _update_mastery(mastery, sub["student_id"], results)
            _update_review_plan(plan, sub["student_id"], submitted_at, results)

        for (student_id, kp), entry in mastery.items():
            conn.execute(
                "INSERT INTO mastery (student_id, knowledge_point, state,"
                " consecutive_high) VALUES (?, ?, ?, ?)",
                (student_id, kp, entry["state"], entry["consecutive_high"]),
            )
        for (student_id, question_id), item in plan.items():
            conn.execute(
                "INSERT INTO review_plan (student_id, question_id, stage, due_at)"
                " VALUES (?, ?, ?, ?)",
                (student_id, question_id, item["stage"],
                 item["due_at"].isoformat()),
            )
