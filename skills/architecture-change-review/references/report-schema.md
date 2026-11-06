# 阶段报告 JSON 数据结构与填报准则

`collect` 生成 `.agent-change-review/drafts/draft-XXX-xxxxxxxxxx.json`。**仅填写业务语义字段**；不要修改 `_internal`、`stats`、`files`，后两项渲染时会重新计算。

## 必填字段

```json
{
  "task": "实现家庭相册 AI 自动剪辑",
  "phase_title": "阶段 2 · 自动剪辑规划链路",
  "system": {
    "mission": "让家庭照片和视频在本机形成可观看的回忆短片。",
    "business_impact": "用户可从相册素材直接生成可预览的剪辑计划。",
    "technical_impact": "新增规划层；入口和媒体读取层沿用原接口。",
    "module_flow": [
      {"name":"移动端 UI","responsibility":"发起创作与展示状态","impact":"indirect","evidence":["app/src/Feature.kt"]},
      {"name":"创作服务","responsibility":"校验请求并编排任务","impact":"direct","evidence":["backend/api/create.go"]},
      {"name":"镜头规划","responsibility":"按时间和人物生成剪辑清单","impact":"direct","evidence":["backend/planner/plan.py"]},
      {"name":"本机媒体存储","responsibility":"读取原始照片和视频","impact":"untouched","evidence":[]}
    ]
  },
  "flow": {
    "label":"自动剪辑主链路",
    "before":["选择照片","直接按时间拼接","导出"],
    "after":["选择照片","筛选片段","生成镜头计划","本地预览/导出"],
    "explanation":"新增镜头筛选与计划步骤，原始素材仍在本机处理。",
    "evidence":["backend/planner/plan.py"]
  },
  "capabilities": [
    {
      "name":"预览候选片段",
      "business":"用户无需手动挑选每段镜头。",
      "technical":"Planner 基于片段时长和评分生成有序时间轴。",
      "acceptance":"导入 10 段素材并检查预览时间轴是否包含候选片段。",
      "evidence":["backend/planner/plan.py:42"]
    }
  ],
  "differences": [
    {
      "title":"从直接拼接到规划后渲染",
      "before":"UI 请求直接触发渲染。",
      "after":"服务先生成可校验的 timeline，然后调用渲染器。",
      "reason":"业务可先预览和重排；代价是增加中间计划对象。",
      "evidence":["backend/planner/plan.py"]
    }
  ],
  "validation": [
    {"item":"单元测试 python -m pytest tests/test_planner.py","status":"passed","detail":"7 个测试通过；仅在实际执行过时填写"},
    {"item":"Android 真机播放","status":"not_run","detail":"尚未在真机验证"}
  ],
  "risks": [
    {"level":"medium","detail":"长视频抽帧耗时尚未压测","evidence":["backend/planner/plan.py"]}
  ],
  "file_notes": {
    "backend/planner/plan.py":"镜头规划的领域入口"
  }
}
```

上述是**结构示例、虚构路径**，不能直接复制到真实项目报告。真正生成时，`render` 会验证 evidence 路径在本阶段 Before 或 After Git 树中存在。

## 字段边界

- `module_flow` 是上层业务入口→业务/领域→数据/基础设施的**逻辑结构**，不是直接按目录排序；2–10 个。标记 `direct/indirect/untouched`。
- `flow.before` 和 `flow.after` 都必须是非空的**节点数组**。即使骨干未变，也应该在变化的节点上体现前后行为。
- `capabilities` 1–5 项；每项 `business/technical/acceptance/evidence` 必填。`acceptance` 可写待执行步骤，但测试状态必须另写真实状态。
- `differences` 1–5 项；每项 `before/after/reason/evidence` 必填。`reason` 同时讲业务价值与技术代价。
- `validation` 状态只能 `passed/failed/not_run/partial`。没有执行过测试，写 `not_run`，不可写 `passed`。
- `risks` 可为空，但不要把“未记录风险”当作“无风险”。
- `evidence` 每项用仓库相对路径，可选追加 `:line`；代码行号只能在源码里核验后再填写。不可引用外部网址代替真实证据文件。
- `file_notes` 是可选的 `{相对路径: 一句话职责}`，不要解释每个机械文件；建议只解释 3–8 个核心文件。
- 任何指标、性能提升、端到端质量、用户效果，如无运行证据，只写预期或待验证。
