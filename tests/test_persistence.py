"""SQLite 文件持久化：关闭重开后数据仍在，勘误纠正依然生效。"""

from datetime import datetime

from examcore import GradingService

T0 = datetime(2026, 4, 1, 9, 0, 0)


def test_file_backed_persistence(tmp_path):
    db = str(tmp_path / "examcore.db")
    svc = GradingService(db)
    q = svc.create_question(5, ["kp"], ["old"])
    p = svc.create_paper([q], 0.5)
    sid = svc.submit("s1", p, {q: "wrong"}, T0)
    svc.close()

    svc2 = GradingService(db)
    r = svc2.get_submission_result(sid)
    assert (r.score, r.total) == (0, 5)
    assert len(svc2.get_review_plan("s1")) == 1

    svc2.issue_erratum(q, 1, new_answers=["old", "wrong"])
    r = svc2.get_submission_result(sid)
    assert (r.score, r.total) == (5, 5)
    assert svc2.get_review_plan("s1") == []
    svc2.close()
