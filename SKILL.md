---
name: architecture-change-review
description: Generate a concise evidence-backed HTML architecture change report during long coding tasks. Trigger after 5-10 effective files, 1000-2000 changed lines, feature milestones, or architecture/API/schema/security changes. Explain top-down module impact, business outcomes crossed with technical implementation, the main before/after flow, core differences, and changed-file tree. Use after coding milestones, before delivery, or on explicit review requests; not for pure Q&A.
compatibility: Requires Git and Python 3.9+. Works as a portable Agent Skill in Codex, Claude Code, ZCode and DeepSeek Harness.
metadata:
  version: "2.0.0"
---

# Architecture Change Review

**目标：开发者 3 分钟内从业务、架构、核心链路理解 Agent 的修改；避免长任务代码失控。**

本 Skill 是**长任务中的增量 Checkpoint**，不是代码修改后的逐文件流水账，也不是自动猜测功能的 diffstat。**同一结论必须由业务专家视角与技术专家视角交叉论证**，并提供文件证据。

## 1. 何时触发

Agent 必须在**任务开始前**记录初始工作树（如果已有阶段状态，保留），在每次批量写入/测试/完成子功能后检查。工具 Hook 可提醒，**但不能取代 Agent 主动检查**。

| 条件 | 动作 |
|---|---|
| 累计 ≥5 有效文件 **或** ≥1,000 有效增删行 | 标记 `due`；最近一个安全业务节点生成阶段报告 |
| 累计 ≥10 有效文件 **或** ≥2,000 有效增删行 | `hard_due`；尽快形成 Checkpoint，不继续无边界积累 |
| 完成独立功能、阶段可验收 | `collect --force`，即使小于阈值 |
| 公共 API、schema、认证权限、架构边界、核心事件流变更 | 立即标记 `check --critical "原因"`，在原子修改完成后报告 |
| 大任务结束 / 用户要求审阅 | 汇总尚未报告的阶段，交付总览 `index.html` |

文件按阶段**唯一路径去重**；行数是有效代码新增+删除，不是代码库总行数。忽略空白格式变化、常见生成物/锁文件。阈值只是提醒，不得切断数据库事务、未完成的方法或构建过程。超过硬阈值依然先完成当前**最小安全单元**。每阶段成功渲染后，新的代码快照成为下阶段基线，不重复计数。

## 2. 首次初始化与检查（项目根目录执行）

先确定当前 Skill 根目录 `SKILL_DIR`，支持：

- Codex / DeepSeek Harness：`.agents/skills/architecture-change-review/`
- Claude Code：`.claude/skills/architecture-change-review/`
- ZCode：`.zcode/skills/architecture-change-review/`

以下统一使用 `$SKILL_DIR/scripts/change_review.py`；如果所在平台未设置 shell 环境变量，请展开成实际相对路径。

```bash
# 在开发任务的第一处代码编辑之前运行；保留原有状态，不覆盖已有阶段
python3 "$SKILL_DIR/scripts/change_review.py" baseline

# 每次完成有意义的代码编辑批次 / 功能子阶段后运行
python3 "$SKILL_DIR/scripts/change_review.py" check

# 识别架构级变更，显式标记优先检查点
python3 "$SKILL_DIR/scripts/change_review.py" check --critical "对外API契约变更"

# 到达安全节点后生成草稿；业务完成 / 用户要求时加 --force
python3 "$SKILL_DIR/scripts/change_review.py" collect --force --reason "完成订单状态流转"
```

`collect` 仅创建 `.agent-change-review/drafts/draft-*.json`（Git 事实骨架），**不能直接生成可信的业务总结**。Agent 必须读取实际修改代码、旧版代码以及必要的调用方，结合项目文档，填写语义字段。

### 关键事实怎么查

1. 调用 `check --full` 获取本阶段全部变更文件及统计；使用草稿的 `_internal.base_tree` 和 `_internal.current_tree` 作为精确时间窗口。
2. 核心 Before：`git show <base_tree>:path/to/file`；After：`git show <current_tree>:path/to/file`。可查 `git diff <base_tree> <current_tree> -- path/to/file`；**不要用工作区当前 HEAD 代替阶段基线**。
3. 先识别系统入口 / 模块分层 / 领域职责 / 依赖 / 数据或事件流，然后才讲文件；跨模块结果必须追踪实际调用链，不可只看文件名。
4. Agent 未能确认的内容标记 **待验证 / 推断**。测试只能写**实际运行过**的命令和结果。

## 3. 填报结构（按用户阅读顺序）

JSON 字段与示例见 `references/report-schema.md`。

**01. 整体架构影响（必须最先出现）**

- 1 句话说明系统目的。
- 自顶向下列 **2–10 个逻辑模块 / 层**（不是机械目录树），每个标记：`direct`（本阶段真实修改）、`indirect`（代码未改但可能受影响）、`untouched`（确认未触及）。
- **业务影响 1 句话 + 技术影响 1 句话**，对应同一项变更；不要扩展无关模块。
- 对最重要的一条端到端链路展示入口→领域逻辑→数据/事件→返回的 **Before / After**。若链路结构未变，说明节点内行为如何变化。

**02. 已完成功能（业务×技术）**

按业务能力归并，不按文件分页。推荐 **1–3 项**；每项应包括：用户/业务行为变化、关键实现方式、可执行验收方法和真实证据文件。**业务承诺不能超出已实现代码**。

**03. 关键 Before / After（技术取舍和业务意义）**

推荐 **1–3 项**，最多 5 项：过去行为 → 现在行为 → 为什么 + 业务/技术取舍 → 证据。优先：跨层职责、状态流转、领域规则、协议、存储、异常处理、幂等。不要对变量重命名、UI 像素微调做大篇幅解读。

**04. 变更路径与验证**

`tree -L` 风格可展开文件树（由 Git 自动生成，代码职责可补充 `file_notes`）。报告必须分清 `passed/failed/not_run/partial`；仅列真实风险，不要套话。

主阅读区目标 **600–1,000 中文字以内**，阶段大可略增。读者先看 01–03，文件级细节折叠展示。

## 4. 生成 HTML / 继续开发

```bash
python3 "$SKILL_DIR/scripts/change_review.py" render \
  --input .agent-change-review/drafts/draft-001-xxxxxxxxxx.json

# 查询已生成的所有阶段和新增尚未报告的改动
python3 "$SKILL_DIR/scripts/change_review.py" status
```

`render` 自动做：必填语义、证据路径、源码快照一致性校验 → `.agent-change-review/reports/phase-001.html` → 同步更新 `index.html` → **仅成功后**推进累计基线。若失败或源代码变化，重新 `collect` 并填写最新草稿。报告离线运行，**不改动 Git 实际暂存区、不自动提交代码**。

长期任务中，始终交付 **总览 `index.html` + 各阶段独立 HTML**：总览汇总所有已完成 Checkpoint，展示最新系统模块架构、主链路和阶段时间线。用户不需要逐个打开散落文件。

## 5. 特殊情况与守则

- 项目开始就有未提交改动：`baseline` 必须在 Agent 开始写代码前运行以排除存量。如果忘记初始化，脚本退回与 HEAD 比较，**可能包含非本次 Agent 的改动**；必须在报告中说明。
- Agent 上下文压缩、跨会话：先 `status`，读取最新 `index.html` 及 `state.json`、最近阶段报告，不重置基线。
- 确定开始**另一个独立任务**：只有在旧任务改动都已报告后，执行 `baseline --new-task --task "新任务"`，自动归档旧 HTML 与草稿到 `history/`，避免把不同任务混入同一总览。
- 多 Agent 同时开发：**优先不同 Git worktree**；同一工作树无法准确归因，并可能引入竞态。
- 不读取/输出密钥与私密数据；默认排除常见 `.env`、凭据、生成物、大型新文件，详见脚本。需要保密仓库时审阅本地 Git 临时对象策略。
- 过程 Hook 只是提醒，不会自动运行 LLM 推理；**是否已交付阶段报告，以 `render` 成功为准**。
- 最终回复仅：`index.html` 路径、1 句业务结果、1 句架构变化、主要未验证事项。不要复制 HTML 的大段正文。
