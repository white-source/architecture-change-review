# Architecture Change Review · 标准 Agent Skill 插件

**v2.0.1** — 大型代码开发任务中按 5–10 个有效文件 / 1,000–2,000 行和业务里程碑设 Checkpoint；通过同一份**离线 HTML**了解"系统架构落点 → 业务成果与技术实现 → 核心 Before/After → 修改文件树与风险"。自动积累多阶段 `index.html`。

本仓库是标准 **Agent Skill 插件市场（marketplace）仓库**：`.claude-plugin/marketplace.json` + `skills/<name>/SKILL.md`，同时兼容 ZCode 与 Claude Code 的插件市场安装；Codex / DeepSeek 等其它 Agent 可用内置安装器或手动复制。

## 安装

### ZCode（桌面端 · 插件市场）

**设置 → 插件市场（Plugin Marketplace）→ 发现 页 → `+` 添加插件市场**，粘贴本仓库地址：

```
https://github.com/white-source/architecture-change-review
```

添加后在发现页找到「架构变更复盘 Architecture Change Review」点 **安装**，然后在新会话的 composer 技能选择器中启用即可。

### Claude Code（/plugin 命令）

```bash
/plugin marketplace add white-source/architecture-change-review
/plugin install architecture-change-review@architecture-change-review
```

### Codex / DeepSeek / 其它 Agent（安装器）

```bash
git clone --depth 1 https://github.com/white-source/architecture-change-review.git /tmp/architecture-change-review

# 换成你的项目路径；--clients all 会建立 .agents/.claude/.zcode/.dsh 四平台的项目级 Skill
python3 /tmp/architecture-change-review/skills/architecture-change-review/scripts/install.py --repo /path/to/your-project --clients all --rules --hooks

# ZCode 如需实际的工具调用后自动检查：明确授权添加用户级 Hook
python3 /tmp/architecture-change-review/skills/architecture-change-review/scripts/install.py --repo /path/to/your-project --clients all --zcode-user-hooks
```

安装器会：安装标准 `.agents/skills/architecture-change-review`，建立 `.claude/skills`、`.zcode/skills`、`.dsh/skills` 的同名 Skill 链接；`--rules` 将持续复盘规则追加到 `AGENTS.md` 和 `CLAUDE.md`；`--hooks` 合并 Codex / Claude 的项目 Hook，不覆盖其它已有条目。若目标 Skill 目录已存在，更新时加 `--update`（请先检查已有修改）。

**注意**：`--zcode-user-hooks` 会复制一份 Skill 到 `~/.zcode/skills/` 并改**用户目录全局设置**，而不是项目文件；没有这项许可时 ZCode 仍能通过插件市场 / 标准 Skill + 项目规则主动检查。DeepSeek Harness 的文件系统 Skill 组件在部分 CLI 构建可能需要手动启用，详见 `integrations/README.md`。

## 用法（在目标项目根目录）

每个新的开发任务可以执行 `baseline --new-task --task "任务名"`，自动归档上一任务的全部阶段到 `.agent-change-review/history/`。如果上一任务还有未报告改动，会拒绝重置，除非明确加 `--discard-pending`。

```bash
# 开发任务开始前执行一次；已有状态则保留
python3 .agents/skills/architecture-change-review/scripts/change_review.py baseline

# 检查文件数 / 行数 / 疑似关键变更
python3 .agents/skills/architecture-change-review/scripts/change_review.py check --full

# 独立功能完成 / 到达安全节点：生成草稿
python3 .agents/skills/architecture-change-review/scripts/change_review.py collect --force --reason "完成登录认证链路"

# Agent 必须阅读本阶段真实新旧代码，再填写草稿语义字段
python3 .agents/skills/architecture-change-review/scripts/change_review.py render --input .agent-change-review/drafts/draft-001-xxxxxxxxxx.json

# HTML 报告路径：
# .agent-change-review/reports/phase-001.html
# .agent-change-review/reports/index.html
```

> 通过插件市场安装时，上述命令由 Agent 按 `SKILL.md` 自动执行，无需手动敲命令；Skill 位于插件安装缓存内（manifest 中 `${CLAUDE_PLUGIN_ROOT}` 指向的位置）。

`collect` 本身不会臆测业务价值；Agent 必须按照 `SKILL.md` 和 `references/report-schema.md` 补齐。HTML 没有任何网络/CDN 依赖。阶段存储放在项目的 `.agent-change-review/`，目录自身 `.gitignore` 不被纳入 Git 变更。数据只保存在本地。需要删除报告时可自行备份和清理该目录；不会修改用户暂存区或提交记录。

## 原则与边界

- **先业务架构，后源代码**：优先解释系统影响和主链路，再展开树级目录。
- **业务与技术交叉**：同一能力同时阐述可验收的业务结果与真实机制。
- **按阶段真实 Git 快照**：多次覆盖文件不会只剩最终 HEAD 的差异；Checkpoint 成功后累计阈值重置。
- **失败不推进**：JSON 不完整、证据路径不存在、源码发生变化时不出报告；重做 `collect`。
- **安全与性能**：忽略已知密钥/生成物/大体积新文件；不使用真实 Git Index；PostToolUse 检查去重节流。非已知机密仍需用户自行审查源码和本地 Git 对象。
- **并发**：优先给不同 Agent 单独 Git worktree，避免代码改动互相混淆。

## 包结构（标准插件市场仓库）

```
├── .claude-plugin/
│   ├── plugin.json                       插件清单（ZCode 兼容读取此格式）
│   └── marketplace.json                  市场目录（ZCode / Claude Code 通用）
└── skills/
    └── architecture-change-review/       标准 Skill 目录
        ├── SKILL.md                      标准 Skill 入口
        ├── scripts/
        │   ├── change_review.py          基线 / 阈值 / 快照 / 草稿 / HTML
        │   ├── hook_adapter.py           Codex / Claude / ZCode Hook 输入输出适配
        │   └── install.py                四平台项目级安装与配置合并
        ├── assets/report.html            离线 HTML 模板
        ├── references/report-schema.md   业务/技术语义 JSON 协议
        ├── integrations/                 Agent 规则与平台 Hook 说明
        ├── tests/                        Git 快照及 HTML 测试（python3 -m pytest tests/）
        └── examples/sample-report.html   虚构演示（仅用于预览）
```

已测试功能与适配声明以 `tests/` 测试结果和各客户端官方文档为准；不是在所有客户端实际运行过完整任务的声明。

## License

[MIT](LICENSE)
