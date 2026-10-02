# task26100333

## 考后判分与学情模块（exam_learning）

纯 Python 库，供考试服务与培训管理后台直接调用，无接口层；持久化只用 SQLite。

### 功能

- 题目版本化：题目可修订出新版本，交卷时记录每题当时使用的版本。
- 勘误：对题目的某个版本换一组可接受答案或作废。勘误后所有受影响的历史
  答卷成绩、知识点掌握状态、复习计划自动纠正，与当初就用正确答案判的一致。
- 判分：作答与可接受答案逐字相同得全部分值，否则 0 分；作废题不计分也不计入总分。
- 知识点掌握：连续三次得分率高于 85% 进入已掌握；已掌握后某次低于 60% 退回。
- 复习计划：答错进入/重置第 1 档（+1 天），到期答对依次升档（+3/7/14 天），
  第 4 档到期后再答对移出计划。

### 用法

```python
from datetime import datetime
from exam_learning import ExamLearningService, Errata

svc = ExamLearningService("exam.db")          # 不传路径则用内存库
q1 = svc.create_question(10, ["代数"], ["A"])
q2 = svc.create_question(10, ["几何"], ["B"])
paper = svc.create_paper([q1, q2], 0.6)       # 及格线 60%

sid = svc.submit("stu1", paper, {q1: "A", q2: "X"}, datetime.now())
svc.apply_errata(version_id, Errata.replace_answers(["X"]))  # 或 Errata.void()

svc.get_submission_result(sid)   # 成绩（含逐题结果）
svc.get_mastery("stu1")          # 知识点掌握状态
svc.get_review_plan("stu1")      # 复习计划
```

### 设计

原始事件（题目版本、答卷、勘误）落库后，成绩、掌握状态、复习计划均为派生
数据：每次交卷或勘误后按交卷时间重放全部答卷重建，因此勘误天然对历史与
未来答卷同时生效，且结果与从头重算严格一致。

### 测试

```bash
python3 -m pytest tests/ -q
```
