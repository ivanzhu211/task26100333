"""SQLite 持久化：关闭后重开，数据与派生结果仍在。"""
from __future__ import annotations

from datetime import datetime

from exam_learning import Errata, ExamLearningService, MasteryState


def test_file_backed_db_survives_reopen(tmp_path):
    db = str(tmp_path / "exam.db")
    svc = ExamLearningService(db)
    q = svc.create_question(10, ["K"], ["A"])
    paper = svc.create_paper([q], 0.6)
    sid = svc.submit("s", paper, {q: "A"}, datetime(2026, 9, 1, 9))
    vid = svc.get_submission_result(sid).question_results[0].version_id
    svc.apply_errata(vid, Errata.replace_answers(["B"]))
    svc.close()

    svc2 = ExamLearningService(db)
    r = svc2.get_submission_result(sid)
    assert (r.score, r.total, r.passed) == (0, 10, False)
    assert svc2.get_review_plan("s")[0].stage == 1
    assert svc2.get_mastery("s")[0].state == MasteryState.UNMASTERED
    sid2 = svc2.submit("s", paper, {q: "B"}, datetime(2026, 9, 2, 9))
    assert svc2.get_submission_result(sid2).score == 10
    svc2.close()
