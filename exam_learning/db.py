"""SQLite 存储层：建表与连接管理。"""
from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    question_id INTEGER PRIMARY KEY AUTOINCREMENT
);

CREATE TABLE IF NOT EXISTS question_versions (
    version_id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL REFERENCES questions(question_id),
    version_no INTEGER NOT NULL,
    score INTEGER NOT NULL,
    knowledge_points TEXT NOT NULL,
    acceptable_answers TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS papers (
    paper_id INTEGER PRIMARY KEY AUTOINCREMENT,
    pass_line REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_items (
    paper_id INTEGER NOT NULL REFERENCES papers(paper_id),
    question_id INTEGER NOT NULL REFERENCES questions(question_id),
    position INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS submissions (
    submission_id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL,
    paper_id INTEGER NOT NULL REFERENCES papers(paper_id),
    submitted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS submission_answers (
    submission_id INTEGER NOT NULL REFERENCES submissions(submission_id),
    question_id INTEGER NOT NULL REFERENCES questions(question_id),
    version_id INTEGER NOT NULL REFERENCES question_versions(version_id),
    answer TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS errata (
    errata_id INTEGER PRIMARY KEY AUTOINCREMENT,
    version_id INTEGER NOT NULL REFERENCES question_versions(version_id),
    errata_type TEXT NOT NULL,
    new_answers TEXT
);

CREATE TABLE IF NOT EXISTS submission_results (
    submission_id INTEGER PRIMARY KEY REFERENCES submissions(submission_id),
    score INTEGER NOT NULL,
    total INTEGER NOT NULL,
    passed INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS question_results (
    submission_id INTEGER NOT NULL REFERENCES submissions(submission_id),
    question_id INTEGER NOT NULL,
    version_id INTEGER NOT NULL,
    answer TEXT NOT NULL,
    voided INTEGER NOT NULL,
    correct INTEGER NOT NULL,
    earned INTEGER NOT NULL,
    full_score INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS mastery (
    student_id TEXT NOT NULL,
    knowledge_point TEXT NOT NULL,
    state TEXT NOT NULL,
    consecutive_high INTEGER NOT NULL,
    PRIMARY KEY (student_id, knowledge_point)
);

CREATE TABLE IF NOT EXISTS review_plan (
    student_id TEXT NOT NULL,
    question_id INTEGER NOT NULL,
    stage INTEGER NOT NULL,
    due_at TEXT NOT NULL,
    PRIMARY KEY (student_id, question_id)
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn
