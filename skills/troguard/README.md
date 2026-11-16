# TroGuard Image Infringement Check

用 TroGuard 检查 POD 印花、服装和跨境电商图片的版权与 TRO 侵权风险。默认**免费、单图、无需配置**，返回完整检测报告，并默认内嵌相关图片。

## 免费单图

```bash
python3 scripts/tro-check.py ./pattern.png
```

- 只接收 1 张图（≤10MB）
- 输出完整单图报告：风险等级、判定、置信度、结论、证据、建议、人工复核
- 结果会默认内嵌原图、案件库同图和图库/电商证据缩略图（最多 3–5 张）
- 同一 IP 同时只能有 1 个检测在跑；每 IP 每日 50 次，全局每日 500 次，每分钟 3 次
- 结果末尾带注册 CTA：注册送 200 盾石，可看历史、批量检测和团队协作
- `--json` 输出完整 batch + cta；`--no-proxy` 绕过代理；`--source skill` 标记来源

## 安装

```bash
npx skills add mind6683b-a11y/troguard-skills@troguard
```

支持 Claude Code、Codex / OpenCode、Cursor、WorkBuddy 等兼容 Agent Skills 的工具。

## 更多能力

需要批量、历史、团队协作时，到 <https://app.troguard.com/> 注册并验证邮箱。本 skill 只负责免费单图报告，批量入口在 app 内。

## 目录

```text
troguard/
├── SKILL.md
├── README.md
├── scripts/
│   └── tro-check.py      # 免费单图 + 检测报告
└── references/
    └── api.md            # 接口、限流、错误
```

## 边界

- 只做图片侧风险筛查，不提供法律意见、诉讼代理或 TRO 应对方案。
- 不承诺覆盖所有权利来源；未命中不代表没有风险。
