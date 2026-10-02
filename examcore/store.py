"""SQLite 持久化层：只负责事件与派生状态的读写。"""

from __future__ import annotations

import json
import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    points INTEGER NOT NULL,
    knowledge_points TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS question_versions (
    question_id INTEGER NOT NULL,
    version_no INTEGER NOT NULL,
    acceptable_answers TEXT NOT NULL,
    PRIMARY KEY (question_id, version_no)
);
CREATE TABLE IF NOT EXISTS errata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL,
    version_no INTEGER NOT NULL,
    kind TEXT NOT NULL,
    new_answers TEXT
);
CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_ids TEXT NOT NULL,
    pass_line REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    paper_id INTEGER NOT NULL,
    submitted_at TEXT NOT NULL,
    answers TEXT NOT NULL,
    question_versions TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS submission_results (
    submission_id INTEGER PRIMARY KEY,
    student_id TEXT NOT NULL,
    score INTEGER NOT NULL,
    total INTEGER NOT NULL,
    rate REAL NOT NULL,
    passed INTEGER NOT NULL,
    details TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mastery (
    student_id TEXT NOT NULL,
    knowledge_point TEXT NOT NULL,
    mastered INTEGER NOT NULL,
    streak INTEGER NOT NULL,
    PRIMARY KEY (student_id, knowledge_point)
);
CREATE TABLE IF NOT EXISTS review_plan (
    student_id TEXT NOT NULL,
    question_id INTEGER NOT NULL,
    tier INTEGER NOT NULL,
    due_at TEXT NOT NULL,
    PRIMARY KEY (student_id, question_id)
);
"""


class Store:
    """SQLite 存储。事件（题目/版本/勘误/答卷）是唯一事实来源，
    派生表（判分结果/掌握状态/复习计划）可由事件重放重建。"""

    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ---- 题目与版本 ----

    def insert_question(self, points: int, knowledge_points: list[str], acceptable_answers: list[str]) -> int:
        cur = self._conn.execute(
            "INSERT INTO questions (points, knowledge_points) VALUES (?, ?)",
            (points, json.dumps(knowledge_points)),
        )
        question_id = cur.lastrowid
        self._conn.execute(
            "INSERT INTO question_versions (question_id, version_no, acceptable_answers) VALUES (?, 1, ?)",
            (question_id, json.dumps(acceptable_answers)),
        )
        self._conn.commit()
        return question_id

    def insert_question_version(self, question_id: int, acceptable_answers: list[str]) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(version_no), 0) AS v FROM question_versions WHERE question_id = ?",
            (question_id,),
        ).fetchone()
        if row["v"] == 0:
            raise KeyError(f"question {question_id} not found")
        version_no = row["v"] + 1
        self._conn.execute(
            "INSERT INTO question_versions (question_id, version_no, acceptable_answers) VALUES (?, ?, ?)",
            (question_id, version_no, json.dumps(acceptable_answers)),
        )
        self._conn.commit()
        return version_no

    def get_question(self, question_id: int) -> tuple[int, list[str]]:
        row = self._conn.execute(
            "SELECT points, knowledge_points FROM questions WHERE id = ?", (question_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"question {question_id} not found")
        return row["points"], json.loads(row["knowledge_points"])

    def get_version_answers(self, question_id: int, version_no: int) -> list[str]:
        row = self._conn.execute(
            "SELECT acceptable_answers FROM question_versions WHERE question_id = ? AND version_no = ?",
            (question_id, version_no),
        ).fetchone()
        if row is None:
            raise KeyError(f"question {question_id} version {version_no} not found")
        return json.loads(row["acceptable_answers"])

    def get_current_version(self, question_id: int) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(version_no), 0) AS v FROM question_versions WHERE question_id = ?",
            (question_id,),
        ).fetchone()
        if row["v"] == 0:
            raise KeyError(f"question {question_id} not found")
        return row["v"]

    # ---- 勘误 ----

    def insert_erratum(self, question_id: int, version_no: int, kind: str, new_answers: list[str] | None) -> None:
        self.get_version_answers(question_id, version_no)  # 校验版本存在
        self._conn.execute(
            "INSERT INTO errata (question_id, version_no, kind, new_answers) VALUES (?, ?, ?, ?)",
            (question_id, version_no, kind, json.dumps(new_answers) if new_answers is not None else None),
        )
        self._conn.commit()

    def get_effective_answers(self, question_id: int, version_no: int) -> list[str] | None:
        """返回该版本当前生效的可接受答案；None 表示已作废。"""
        row = self._conn.execute(
            "SELECT kind, new_answers FROM errata WHERE question_id = ? AND version_no = ? ORDER BY id DESC LIMIT 1",
            (question_id, version_no),
        ).fetchone()
        if row is None:
            return self.get_version_answers(question_id, version_no)
        if row["kind"] == "void":
            return None
        return json.loads(row["new_answers"])

    # ---- 试卷 ----

    def insert_paper(self, question_ids: list[int], pass_line: float) -> int:
        cur = self._conn.execute(
            "INSERT INTO papers (question_ids, pass_line) VALUES (?, ?)",
            (json.dumps(question_ids), pass_line),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_paper(self, paper_id: int) -> tuple[list[int], float]:
        row = self._conn.execute(
            "SELECT question_ids, pass_line FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"paper {paper_id} not found")
        return json.loads(row["question_ids"]), row["pass_line"]

    # ---- 答卷事件 ----

    def insert_submission(
        self,
        student_id: str,
        paper_id: int,
        submitted_at: str,
        answers: dict[int, str],
        question_versions: dict[int, int],
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO submissions (student_id, paper_id, submitted_at, answers, question_versions)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                student_id,
                paper_id,
                submitted_at,
                json.dumps({str(k): v for k, v in answers.items()}),
                json.dumps({str(k): v for k, v in question_versions.items()}),
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_submission(self, submission_id: int) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT * FROM submissions WHERE id = ?", (submission_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"submission {submission_id} not found")
        return row

    def list_submissions(self, student_id: str | None = None) -> list[sqlite3.Row]:
        if student_id is None:
            return self._conn.execute(
                "SELECT * FROM submissions ORDER BY submitted_at, id"
            ).fetchall()
        return self._conn.execute(
            "SELECT * FROM submissions WHERE student_id = ? ORDER BY submitted_at, id",
            (student_id,),
        ).fetchall()

    def students_using_version(self, question_id: int, version_no: int) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT student_id FROM submissions WHERE json_extract(question_versions, ?) = ?",
            (f"$.{question_id}", version_no),
        ).fetchall()
        return [r["student_id"] for r in rows]

    # ---- 派生状态 ----

    def save_submission_result(
        self,
        submission_id: int,
        student_id: str,
        score: int,
        total: int,
        rate: float,
        passed: bool,
        details: list[dict],
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO submission_results"
            " (submission_id, student_id, score, total, rate, passed, details)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (submission_id, student_id, score, total, rate, int(passed), json.dumps(details)),
        )
        self._conn.commit()

    def get_submission_result(self, submission_id: int) -> sqlite3.Row:
        row = self._conn.execute(
            "SELECT * FROM submission_results WHERE submission_id = ?", (submission_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"result for submission {submission_id} not found")
        return row

    def get_mastery_row(self, student_id: str, knowledge_point: str) -> tuple[bool, int]:
        row = self._conn.execute(
            "SELECT mastered, streak FROM mastery WHERE student_id = ? AND knowledge_point = ?",
            (student_id, knowledge_point),
        ).fetchone()
        if row is None:
            return False, 0
        return bool(row["mastered"]), row["streak"]

    def save_mastery(self, student_id: str, knowledge_point: str, mastered: bool, streak: int) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO mastery (student_id, knowledge_point, mastered, streak)"
            " VALUES (?, ?, ?, ?)",
            (student_id, knowledge_point, int(mastered), streak),
        )
        self._conn.commit()

    def list_mastery(self, student_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT knowledge_point, mastered, streak FROM mastery WHERE student_id = ?"
            " ORDER BY knowledge_point",
            (student_id,),
        ).fetchall()

    def get_review_item(self, student_id: str, question_id: int) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT tier, due_at FROM review_plan WHERE student_id = ? AND question_id = ?",
            (student_id, question_id),
        ).fetchone()

    def save_review_item(self, student_id: str, question_id: int, tier: int, due_at: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO review_plan (student_id, question_id, tier, due_at)"
            " VALUES (?, ?, ?, ?)",
            (student_id, question_id, tier, due_at),
        )
        self._conn.commit()

    def delete_review_item(self, student_id: str, question_id: int) -> None:
        self._conn.execute(
            "DELETE FROM review_plan WHERE student_id = ? AND question_id = ?",
            (student_id, question_id),
        )
        self._conn.commit()

    def list_review_plan(self, student_id: str) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT question_id, tier, due_at FROM review_plan WHERE student_id = ? ORDER BY question_id",
            (student_id,),
        ).fetchall()

    def clear_derived_for_student(self, student_id: str) -> None:
        """删除某学员全部派生状态，供勘误后重放重建。"""
        self._conn.execute("DELETE FROM submission_results WHERE student_id = ?", (student_id,))
        self._conn.execute("DELETE FROM mastery WHERE student_id = ?", (student_id,))
        self._conn.execute("DELETE FROM review_plan WHERE student_id = ?", (student_id,))
        self._conn.commit()
