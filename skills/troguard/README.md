# TroGuard Agent Skill

[![skills.sh](https://skills.sh/b/mind6683b-a11y/troguard-skills)](https://skills.sh/mind6683b-a11y/troguard-skills)

给 AI Agent 用的 TroGuard 图片侵权检测能力：默认**免费、免 API Key、一次 1 张图**，返回完整单图风险报告；需要批量/历史时再注册并使用 API Key。

官方维护：图盾 TroGuard（<https://www.troguard.com>）。只从官方仓库安装。

适用于 Claude Code、Codex / OpenCode、Cursor 等兼容 Agent Skills 标准的工具。

## 安装

```bash
npx skills add mind6683b-a11y/troguard-skills@troguard
```

## 免费单图（默认）

不需要注册、不需要 API Key：

```bash
python3 skills/troguard/scripts/tro-check.py ./pattern.png
```

- 只接收 1 张图（≤10MB），输出完整单图报告：风险等级、判定、置信度、结论、证据、建议
- 同一 IP 同时只能有 1 个检测在跑；每 IP 每日免费次数有限（默认 3 次）
- 结果末尾带注册 CTA：注册送 200 盾石，可看历史、批量检测和团队协作
- `--json` 输出完整 batch + cta；`--no-proxy` 绕过代理；`--free` 强制免费路径

## API Key 批量（注册后）

注册并验证邮箱送 200 盾石，不需要信用卡。批量 1 盾石/张，失败任务退还。

1. 登录 <https://app.troguard.com/>，切换到要计费的团队。
2. 左侧「Agent → Agent Skill」→ 创建 API Key；完整 Key 只显示一次。
3. 安全保存 Key（不回显，写入 `~/.config/troguard.env`，权限 600）：

```bash
mkdir -p ~/.config
read -rsp "TroGuard API Key: " TROGUARD_API_KEY && echo
(umask 077 && printf "TROGUARD_API_KEY='%s'\n" "$TROGUARD_API_KEY" > ~/.config/troguard.env)
unset TROGUARD_API_KEY
```

脚本会自动读取 `~/.config/troguard.env`；也可以直接 `export TROGUARD_API_KEY='trk_...'`。不会用终端的话，可以把 Key 发给 Agent，让 Agent 帮你写入配置文件；配置完成后不要在聊天里回显完整 Key。

批量运行：

```bash
python3 skills/troguard/scripts/tro-check.py ./a.png ./b.jpg --name "上新自查"
```

- 1–200 张；每张 ≤10MB；请求体 ≤82MB
- 支持 `--name`、`--json`、`--env-file`、`--timeout`、`--no-proxy`
- 批量结果按批次汇总；`--json` 输出完整批次

## 手动安装（zip）

下载 [troguard-skill.zip](https://www.troguard.com/downloads/troguard-skill.zip)，解压后把 `troguard/` 放到 Agent 的 skills 目录，例如 `~/.agents/skills/` 或 `~/.claude/skills/`。

## 内容

```
skills/troguard/
  SKILL.md              # Agent 指令（免费单图优先）
  scripts/tro-check.py  # 免费单图 + API Key 批量助手
  references/api.md     # 完整接口、字段、限流和错误
```

## 计费与边界

- 免费单图不扣盾石；1 张/次、单 IP 单并发、每 IP 每日限额。
- API Key 批量 1 盾石/张，失败任务退还；余额不足返回 402 `insufficient_credits`。
- 结果是风险筛查线索，不构成法律意见；不承诺覆盖所有权利来源。
