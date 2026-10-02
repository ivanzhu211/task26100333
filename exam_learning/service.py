"""对外服务门面：供考试服务与培训管理后台直接调用。"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from .db import connect
from .engine import rebuild_all
from .models import (
    Errata,
    ErrataType,
    MasteryStatus,
    MasteryState,
    QuestionResult,
    ReviewItem,
    SubmissionResult,
)


class ExamLearningService:
    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn: sqlite3.Connection = connect(db_path)

    def close(self) -> None:
        self._conn.close()

    def create_question(
        self,
        score: int,
        knowledge_points: list[str],
        acceptable_answers: list[str],
    ) -> int:
        """创建题目（含首个版本），返回 question_id。"""
        with self._conn:
            cur = self._conn.execute("INSERT INTO questions DEFAULT VALUES")
            question_id = cur.lastrowid
            self._conn.execute(
                "INSERT INTO question_versions (question_id, version_no, score,"
                " knowledge_points, acceptable_answers) VALUES (?, 1, ?, ?, ?)",
                (question_id, score, json.dumps(knowledge_points),
                 json.dumps(acceptable_answers)),
            )
        return question_id

    def revise_question(
        self,
        question_id: int,
        score: int,
        knowledge_points: list[str],
        acceptable_answers: list[str],
    ) -> int:
        """为题目修订出新版本，返回 version_id。不影响旧答卷。"""
        with self._conn:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(version_no), 0) AS max_no"
                " FROM question_versions WHERE question_id = ?",
                (question_id,),
            ).fetchone()
            if row is None or row["max_no"] == 0:
                raise ValueError(f"题目不存在: {question_id}")
            cur = self._conn.execute(
                "INSERT INTO question_versions (question_id, version_no, score,"
                " knowledge_points, acceptable_answers) VALUES (?, ?, ?, ?, ?)",
                (question_id, row["max_no"] + 1, score,
                 json.dumps(knowledge_points), json.dumps(acceptable_answers)),
            )
        return cur.lastrowid

    def create_paper(self, question_ids: list[int], pass_line: float) -> int:
        """组卷：一组题目加一条及格线，返回 paper_id。"""
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO papers (pass_line) VALUES (?)", (pass_line,)
            )
            paper_id = cur.lastrowid
            for position, question_id in enumerate(question_ids):
                self._conn.execute(
                    "INSERT INTO paper_items (paper_id, question_id, position)"
                    " VALUES (?, ?, ?)",
                    (paper_id, question_id, position),
                )
        return paper_id

    def submit(
        self,
        student_id: str,
        paper_id: int,
        answers: dict[int, str],
        submitted_at: datetime,
    ) -> int:
        """交卷：记录每题当时的版本与作答，返回 submission_id。"""
        items = self._conn.execute(
            "SELECT question_id FROM paper_items WHERE paper_id = ?"
            " ORDER BY position",
            (paper_id,),
        ).fetchall()
        if not items:
            raise ValueError(f"试卷不存在或没有题目: {paper_id}")
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO submissions (student_id, paper_id, submitted_at)"
                " VALUES (?, ?, ?)",
                (student_id, paper_id, submitted_at.isoformat()),
            )
            submission_id = cur.lastrowid
            for item in items:
                version = self._conn.execute(
                    "SELECT version_id FROM question_versions"
                    " WHERE question_id = ? ORDER BY version_no DESC LIMIT 1",
                    (item["question_id"],),
                ).fetchone()
                self._conn.execute(
                    "INSERT INTO submission_answers (submission_id, question_id,"
                    " version_id, answer) VALUES (?, ?, ?, ?)",
                    (submission_id, item["question_id"], version["version_id"],
                     answers.get(item["question_id"], "")),
                )
            rebuild_all(self._conn)
        return submission_id

    def apply_errata(self, version_id: int, errata: Errata) -> None:
        """对题目的某个版本施加勘误，自动纠正所有受影响的历史结果。"""
        row = self._conn.execute(
            "SELECT version_id FROM question_versions WHERE version_id = ?",
            (version_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"题目版本不存在: {version_id}")
        new_answers = (
            json.dumps(list(errata.new_answers))
            if errata.errata_type == ErrataType.REPLACE_ANSWERS
            else None
        )
        with self._conn:
            self._conn.execute(
                "INSERT INTO errata (version_id, errata_type, new_answers)"
                " VALUES (?, ?, ?)",
                (version_id, errata.errata_type.value, new_answers),
            )
            rebuild_all(self._conn)

    def get_submission_result(self, submission_id: int) -> SubmissionResult:
        sub = self._conn.execute(
            "SELECT submission_id, student_id, paper_id, submitted_at"
            " FROM submissions WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()
        if sub is None:
            raise ValueError(f"答卷不存在: {submission_id}")
        result = self._conn.execute(
            "SELECT score, total, passed FROM submission_results"
            " WHERE submission_id = ?",
            (submission_id,),
        ).fetchone()
        rows = self._conn.execute(
            "SELECT question_id, version_id, answer, voided, correct, earned,"
            " full_score FROM question_results WHERE submission_id = ?"
            " ORDER BY question_id",
            (submission_id,),
        ).fetchall()
        return SubmissionResult(
            submission_id=sub["submission_id"],
            student_id=sub["student_id"],
            paper_id=sub["paper_id"],
            submitted_at=datetime.fromisoformat(sub["submitted_at"]),
            score=result["score"],
            total=result["total"],
            passed=bool(result["passed"]),
            question_results=tuple(
                QuestionResult(
                    question_id=r["question_id"],
                    version_id=r["version_id"],
                    answer=r["answer"],
                    voided=bool(r["voided"]),
                    correct=bool(r["correct"]),
                    earned=r["earned"],
                    full_score=r["full_score"],
                )
                for r in rows
            ),
        )

    def get_mastery(self, student_id: str) -> list[MasteryStatus]:
        rows = self._conn.execute(
            "SELECT student_id, knowledge_point, state, consecutive_high"
            " FROM mastery WHERE student_id = ? ORDER BY knowledge_point",
            (student_id,),
        ).fetchall()
        return [
            MasteryStatus(
                student_id=r["student_id"],
                knowledge_point=r["knowledge_point"],
                state=MasteryState(r["state"]),
                consecutive_high=r["consecutive_high"],
            )
            for r in rows
        ]

    def get_review_plan(self, student_id: str) -> list[ReviewItem]:
        rows = self._conn.execute(
            "SELECT student_id, question_id, stage, due_at FROM review_plan"
            " WHERE student_id = ? ORDER BY question_id",
            (student_id,),
        ).fetchall()
        return [
            ReviewItem(
                student_id=r["student_id"],
                question_id=r["question_id"],
                stage=r["stage"],
                due_at=datetime.fromisoformat(r["due_at"]),
            )
            for r in rows
        ]
