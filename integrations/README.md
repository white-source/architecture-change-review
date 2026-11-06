# 四种 Agent / Hook 适配

| 工具 | Skill 搜索路径（项目级） | 过程检查 |
|---|---|---|
| Codex | `.agents/skills/architecture-change-review/` | `PostToolUse` + `Stop`（`.codex/hooks.json`，需 `/hooks` 审核信任） |
| Claude Code | `.claude/skills/architecture-change-review/` | `PostToolUse` + `Stop`（`.claude/settings.json`） |
| ZCode | `.zcode/skills/architecture-change-review/` | 用户级 `~/.zcode/cli/config.json` Hook；**项目级 Hook 当前不执行** |
| DeepSeek Harness | `.agents/skills/` 或 `.dsh/skills/` | 默认 Agent 遵循 `AGENTS.md` 主动 `check`；Skill 本身不是 Hook |

运行 `python3 scripts/install.py --repo /path/to/repo --clients all --rules --hooks`，将共用 Skill 安装到 `.agents/skills`，并为其它平台使用符号链接（不支持时复制）。当运行中的客户端支持工具事件时，Hook 在工具写入后检测规模并**给 Agent 注入阶段提醒**，不是自行发起模型请求。

如果你确实要启用 **ZCode 用户级 Hook**（会修改 `~/.zcode/cli/config.json`，影响当前账号下所有 ZCode 工作区），再加 `--zcode-user-hooks`。安装器还会复制一份稳定的脚本到 `~/.zcode/skills/architecture-change-review/`，避免源项目移动后全局 Hook 失效。工具进程只对已执行 `baseline` 的仓库进行检查。ZCode 需要启动新会话才能保证读取新配置。ZCode 不运行普通项目 `.zcode/config.json` 中的 Hook。

两种 Hook 的差别：

- `PostToolUse`：统计 Git 工作树与阶段基线的差异，达到新阈值时向 Agent 追加上下文。**不生成报告**，不打断正在执行的原子工作。
- `Stop`：若有未报告的到期阶段且当前没有 `stop_hook_active`，可触发一次继续处理提醒。为避免循环，会检测 Hook 已激活状态。

不建议高频遍历整份 diff。脚本默认 PostToolUse 4 秒节流、按阈值桶去重，只取 Git 文件元信息。

## 客户端兼容性说明

- Skill 的标准格式依据 [Agent Skills](https://agentskills.io/specification)。
- Codex Hook 事件与 JSON 输出契约：<https://learn.chatgpt.com/docs/hooks>。
- Claude Code 项目级 Hook：<https://code.claude.com/docs/en/hooks>。
- ZCode 项目级 Skill、用户级 Hook：<https://zcode.z.ai/en/docs/skill>、<https://zcode.z.ai/en/docs/hooks>。
- DeepSeek Harness 本地 Skill Provider：<https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/skills.md>。部分 CLI 构建默认不启用 Skill Provider，需要先启用。

Hook 执行任意本地代码，部署前审阅脚本。安装不自动授权执行、不跳过安全审批。Hook 不保证每一类工具都可被捕获，Agent 主动 `check` 仍然必要。
