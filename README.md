# examcore：考后判分与学情模块

面向公司内训平台的 Python 库，由上层考试服务 / 培训管理后台直接调用（无接口层），
数据存 SQLite。核心能力：**勘误发布后，所有受影响的历史结果自动纠正**，
与当初就用正确答案判出来的结果一致。

## 功能

- **判分**：作答与题目当前版本任一可接受答案逐字相同得全部分值，否则 0 分；
  得分率达到试卷及格线即通过。
- **题目版本**：题目可修订出新版本，交卷时记录每题当时的版本；修订不影响旧答卷。
- **勘误追溯**：针对题目的某个版本换答案或作废。作废题不计分、不计入总分，
  掌握情况与复习计划中当作没答过。勘误只影响用该版本作答的答卷（含以后交的）。
  实现方式：事件（版本 / 勘误 / 答卷）是唯一事实来源，勘误后清空受影响学员的
  派生状态并按交卷时间重放其全部答卷重建。
- **知识点掌握**：按交卷时间，每份含该知识点未作废题目的答卷算一次作答；
  连续 3 次得分率严格高于 85% 进入已掌握；已掌握后某次低于 60% 退回未掌握；
  60%~85% 之间不改变状态。
- **复习计划**：按学员 + 题目（不分版本）。答错进入 / 重置到第 1 档（+1 天）；
  到期后答对升档（依次 +3 / +7 / +14 天）；第 4 档到期后再答对移出计划；
  没到期答对不升档。

## 用法

```python
from datetime import datetime
from examcore import GradingService

svc = GradingService("examcore.db")      # 或不传参用内存库
q1 = svc.create_question(5, ["algebra"], ["A"])
q2 = svc.create_question(10, ["geometry"], ["g1"])
paper = svc.create_paper([q1, q2], pass_line=0.6)

sid = svc.submit("alice", paper, {q1: "A", q2: "bad"}, datetime.now())

svc.revise_question(q1, ["A", "A2"])           # 修订：不影响旧答卷
svc.issue_erratum(q2, 1, new_answers=["g1", "G1"])  # 勘误：换答案，自动纠正历史
svc.issue_erratum(q2, 1, void=True)                 # 勘误：作废

result = svc.get_submission_result(sid)   # SubmissionResult(score/total/rate/passed/details)
mastery = svc.get_mastery("alice")        # list[MasteryState]
plan = svc.get_review_plan("alice")       # list[ReviewItem]
svc.close()
```

## 结构

- `examcore/models.py` — 领域模型（判分结果 / 掌握状态 / 复习条目）
- `examcore/store.py` — SQLite 持久化（事件表 + 派生表）
- `examcore/grading.py` — 逐题判分与汇总
- `examcore/mastery.py` — 知识点掌握状态机
- `examcore/review.py` — 复习计划档位推进
- `examcore/service.py` — 门面 API 与勘误重放

## 测试

```bash
python3 -m pytest tests/ -q
```

`tests/test_acceptance.py` 覆盖验收场景：多名学员先后交卷、题目修订版本、
对旧版本换答案、另一道题作废、继续交卷；最终每个学员的答卷成绩、知识点掌握、
复习计划均与独立实现的"按最终答案从头重算"结果逐一比对一致。
