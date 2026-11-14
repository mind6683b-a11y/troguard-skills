# TroGuard Agent Skill

[![skills.sh](https://skills.sh/b/mind6683b-a11y/troguard-skills)](https://skills.sh/mind6683b-a11y/troguard-skills)

给 AI Agent 用的 TroGuard 图片侵权检测能力：上传印花、主图、详情页素材，返回版权与 TRO 风险等级、证据来源和案件线索。

官方维护：图盾 TroGuard（<https://www.troguard.com>）。只从官方仓库安装。

适用于 Claude Code、Codex / OpenCode、Cursor 等兼容 Agent Skills 标准的工具。

## 安装

```bash
npx skills add mind6683b-a11y/troguard-skills@troguard
```

## 配置

1. 登录 <https://app.troguard.com/>，切换到要计费的团队。
2. 左侧「Agent → Agent Skill」→ 创建 API Key；完整 Key 只显示一次。
3. 设置环境变量：

```bash
export TROGUARD_API_KEY='trk_...'
# 可选，默认 https://app.troguard.com
export TROGUARD_API_BASE='https://app.troguard.com'
```

不要在聊天、仓库或日志里保存完整 Key；泄露后在门户立即吊销。

## 使用

安装后直接让 Agent 检查图片，例如：

> 帮我检查这两张印花有没有 TRO 或版权风险：./a.png ./b.jpg

也可以手动运行 skill 自带脚本：

```bash
python3 skills/troguard/scripts/tro-check.py ./a.png ./b.jpg --name "上新自查"
```

脚本只用 Python 3.8+ 标准库，会批量提交并轮询到批次结束，输出风险摘要。`--json` 输出完整批次，`--env-file` 读取 Key 文件，`--no-proxy` 绕过代理。

## 内容

```
skills/troguard/
  SKILL.md              # Agent 指令
  scripts/tro-check.py  # 批量提交 + 轮询助手
  references/api.md     # 完整接口、字段、限流和错误
```

## 计费与边界

- 1 盾石/张，失败任务退还；余额不足返回 402 `insufficient_credits`。
- 结果是风险筛查线索，不构成法律意见；不承诺覆盖所有权利来源。
- 402 按次支付通道已停用，公开接口只使用 API Key。
