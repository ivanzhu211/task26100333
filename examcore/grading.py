"""判分逻辑：根据题目版本与生效勘误，对一份答卷判分。"""

from __future__ import annotations

from examcore.models import QuestionResult


def grade_answers(
    paper_question_ids: list[int],
    question_versions: dict[int, int],
    answers: dict[int, str],
    question_meta: dict[int, tuple[int, list[str]]],
    effective_answers: dict[tuple[int, int], list[str] | None],
) -> list[QuestionResult]:
    """对一份答卷逐题判分。

    effective_answers: (question_id, version_no) -> 可接受答案列表；
    值为 None 表示该版本已被勘误作废（不计分、不计入总分）。
    作答与任一可接受答案逐字相同即得全部分值，否则 0 分。
    """
    results: list[QuestionResult] = []
    for question_id in paper_question_ids:
        version_no = question_versions[question_id]
        points, _knowledge_points = question_meta[question_id]
        accepted = effective_answers[(question_id, version_no)]
        if accepted is None:
            results.append(
                QuestionResult(
                    question_id=question_id,
                    version_no=version_no,
                    voided=True,
                    correct=False,
                    earned=0,
                    points=points,
                )
            )
            continue
        correct = answers.get(question_id) in accepted
        results.append(
            QuestionResult(
                question_id=question_id,
                version_no=version_no,
                voided=False,
                correct=correct,
                earned=points if correct else 0,
                points=points,
            )
        )
    return results


def summarize(results: list[QuestionResult], pass_line: float) -> tuple[int, int, float, bool]:
    """汇总一份答卷的得分、总分、得分率与是否通过。作废题不计入。"""
    score = sum(r.earned for r in results if not r.voided)
    total = sum(r.points for r in results if not r.voided)
    rate = score / total if total > 0 else 0.0
    return score, total, rate, rate >= pass_line
