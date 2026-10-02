"""对上层（考试服务 / 培训管理后台）暴露的门面 API。"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime

from examcore.grading import grade_answers, summarize
from examcore.mastery import update_mastery
from examcore.models import MasteryState, QuestionResult, ReviewItem, SubmissionResult
from examcore.review import update_review
from examcore.store import Store


class GradingService:
    """考后判分与学情模块入口。数据存 SQLite，无接口层。

    事件（题目版本、勘误、答卷）是唯一事实来源；判分结果、知识点掌握、
    复习计划均为派生状态。勘误发布后，受影响学员的派生状态会被清空，
    并按交卷时间重放其全部答卷重建，效果等同于当初就用最终答案判分。
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._store = Store(db_path)

    def close(self) -> None:
        self._store.close()

    def __enter__(self) -> "GradingService":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- 题目与试卷 ----

    def create_question(
        self,
        points: int,
        knowledge_points: list[str],
        acceptable_answers: list[str],
    ) -> int:
        """创建题目（初始版本为 1），返回 question_id。"""
        if points <= 0:
            raise ValueError("points must be a positive integer")
        if not knowledge_points:
            raise ValueError("knowledge_points must not be empty")
        if not acceptable_answers:
            raise ValueError("acceptable_answers must not be empty")
        return self._store.insert_question(points, knowledge_points, acceptable_answers)

    def revise_question(self, question_id: int, acceptable_answers: list[str]) -> int:
        """修订题目，产生新版本，返回版本号。修订不算勘误，不影响旧答卷。"""
        if not acceptable_answers:
            raise ValueError("acceptable_answers must not be empty")
        return self._store.insert_question_version(question_id, acceptable_answers)

    def create_paper(self, question_ids: list[int], pass_line: float) -> int:
        """组卷，pass_line 为及格得分率（如 0.6），返回 paper_id。"""
        if not question_ids:
            raise ValueError("question_ids must not be empty")
        if not 0.0 <= pass_line <= 1.0:
            raise ValueError("pass_line must be within [0, 1]")
        for question_id in question_ids:
            self._store.get_question(question_id)  # 校验题目存在
        return self._store.insert_paper(question_ids, pass_line)

    # ---- 交卷 ----

    def submit(
        self,
        student_id: str,
        paper_id: int,
        answers: dict[int, str],
        submitted_at: datetime,
    ) -> int:
        """交卷：记录每题当前版本，判分并更新学情，返回 submission_id。"""
        paper_question_ids, _pass_line = self._store.get_paper(paper_id)
        question_versions = {
            qid: self._store.get_current_version(qid) for qid in paper_question_ids
        }
        submission_id = self._store.insert_submission(
            student_id,
            paper_id,
            submitted_at.isoformat(),
            answers,
            question_versions,
        )
        self._process_submission(
            submission_id=submission_id,
            student_id=student_id,
            paper_id=paper_id,
            submitted_at=submitted_at,
            answers={int(k): v for k, v in answers.items()},
            question_versions=question_versions,
        )
        return submission_id

    # ---- 勘误 ----

    def issue_erratum(
        self,
        question_id: int,
        version_no: int,
        new_answers: list[str] | None = None,
        void: bool = False,
    ) -> None:
        """对题目的某个版本发布勘误（换答案或作废）。

        只影响用该版本作答的答卷（已交的和以后交的）。发布后自动重放
        受影响学员的答卷，纠正历史成绩、知识点掌握与复习计划。
        """
        if void:
            kind, answers_payload = "void", None
        else:
            if not new_answers:
                raise ValueError("new_answers must not be empty unless void=True")
            kind, answers_payload = "replace", new_answers
        self._store.insert_erratum(question_id, version_no, kind, answers_payload)
        for student_id in self._store.students_using_version(question_id, version_no):
            self._replay_student(student_id)

    # ---- 查询 ----

    def get_submission_result(self, submission_id: int) -> SubmissionResult:
        row = self._store.get_submission_result(submission_id)
        sub = self._store.get_submission(submission_id)
        details = tuple(
            QuestionResult(**item) for item in json.loads(row["details"])
        )
        return SubmissionResult(
            submission_id=row["submission_id"],
            student_id=row["student_id"],
            paper_id=sub["paper_id"],
            submitted_at=datetime.fromisoformat(sub["submitted_at"]),
            score=row["score"],
            total=row["total"],
            rate=row["rate"],
            passed=bool(row["passed"]),
            details=details,
        )

    def get_mastery(self, student_id: str) -> list[MasteryState]:
        return [
            MasteryState(
                knowledge_point=row["knowledge_point"],
                mastered=bool(row["mastered"]),
                streak=row["streak"],
            )
            for row in self._store.list_mastery(student_id)
        ]

    def get_review_plan(self, student_id: str) -> list[ReviewItem]:
        return [
            ReviewItem(
                question_id=row["question_id"],
                tier=row["tier"],
                due_at=datetime.fromisoformat(row["due_at"]),
            )
            for row in self._store.list_review_plan(student_id)
        ]

    # ---- 内部：判分与学情更新 ----

    def _process_submission(
        self,
        submission_id: int,
        student_id: str,
        paper_id: int,
        submitted_at: datetime,
        answers: dict[int, str],
        question_versions: dict[int, int],
    ) -> None:
        paper_question_ids, pass_line = self._store.get_paper(paper_id)
        question_meta = {qid: self._store.get_question(qid) for qid in paper_question_ids}
        effective = {
            (qid, ver): self._store.get_effective_answers(qid, ver)
            for qid, ver in question_versions.items()
        }
        results = grade_answers(
            paper_question_ids, question_versions, answers, question_meta, effective
        )
        score, total, rate, passed = summarize(results, pass_line)
        self._store.save_submission_result(
            submission_id,
            student_id,
            score,
            total,
            rate,
            passed,
            [asdict(r) for r in results],
        )
        self._update_mastery(student_id, results, question_meta)
        self._update_review_plan(student_id, results, submitted_at)

    def _update_mastery(
        self,
        student_id: str,
        results: list[QuestionResult],
        question_meta: dict[int, tuple[int, list[str]]],
    ) -> None:
        kp_earned: dict[str, int] = {}
        kp_total: dict[str, int] = {}
        for r in results:
            if r.voided:
                continue
            for kp in question_meta[r.question_id][1]:
                kp_earned[kp] = kp_earned.get(kp, 0) + r.earned
                kp_total[kp] = kp_total.get(kp, 0) + r.points
        for kp, total in kp_total.items():
            rate = kp_earned[kp] / total if total > 0 else 0.0
            mastered, streak = self._store.get_mastery_row(student_id, kp)
            mastered, streak = update_mastery(mastered, streak, rate)
            self._store.save_mastery(student_id, kp, mastered, streak)

    def _update_review_plan(
        self,
        student_id: str,
        results: list[QuestionResult],
        submitted_at: datetime,
    ) -> None:
        for r in results:
            if r.voided:
                continue
            row = self._store.get_review_item(student_id, r.question_id)
            item = (
                ReviewItem(
                    question_id=r.question_id,
                    tier=row["tier"],
                    due_at=datetime.fromisoformat(row["due_at"]),
                )
                if row is not None
                else None
            )
            new_item = update_review(item, r.question_id, r.correct, submitted_at)
            if new_item is None:
                self._store.delete_review_item(student_id, r.question_id)
            else:
                self._store.save_review_item(
                    student_id, r.question_id, new_item.tier, new_item.due_at.isoformat()
                )

    def _replay_student(self, student_id: str) -> None:
        """清空学员派生状态，按交卷时间重放其全部答卷重建。"""
        self._store.clear_derived_for_student(student_id)
        for sub in self._store.list_submissions(student_id):
            self._process_submission(
                submission_id=sub["id"],
                student_id=student_id,
                paper_id=sub["paper_id"],
                submitted_at=datetime.fromisoformat(sub["submitted_at"]),
                answers={int(k): v for k, v in json.loads(sub["answers"]).items()},
                question_versions={
                    int(k): v for k, v in json.loads(sub["question_versions"]).items()
                },
            )
