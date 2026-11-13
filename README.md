# GitHub 热门开源项目 → Telegram 推送机器人

自动抓取近期热门 GitHub 开源项目，使用 GitHub Models (gpt-4o-mini) 生成精美推荐文案，并以 **HTML** 格式推送到 Telegram 频道。

## 功能特点

- 每天自动运行（UTC 01:00 / 北京时间 09:00）
- 支持手动触发
- 使用本地 `pushed_history.json` 去重，避免重复推送
- AI 生成带 Emoji 的精美 **HTML** 文案（支持加粗、链接等）
- 每次最多推送 1–2 个新项目
- 搜索时自动排除 fork，优先真正的新项目
- HTML 解析失败时自动降级为纯文本，保证消息能发出

## 配置步骤

### 1. 添加 GitHub Secrets

进入仓库 **Settings → Secrets and variables → Actions**，添加以下三个 Secrets：

| Secret 名称 | 说明 |
|-------------|------|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token（从 @BotFather 获取） |
| `TELEGRAM_CHANNEL_ID` | 目标频道 ID（例如 `-100xxxxxxxxxx`） |
| `GH_TOKEN` | 你的 GitHub Personal Access Token（需要 `models:read` 权限，用于调用 GitHub Models） |

### 2. 启用 GitHub Actions

仓库创建后 Actions 默认可用。你可以：

- 等待每天自动运行
- 或进入 **Actions** 页面，手动运行 `Daily GitHub Trending Push` workflow

### 3. Telegram 频道设置

1. 创建 Telegram 频道
2. 将你的 Bot 添加为频道管理员（需要发送消息权限）
3. 获取频道 ID（可使用 @userinfobot 或类似工具）

## 文件说明

- `main.py`：核心逻辑（HTML 消息生成 + 推送）
- `requirements.txt`：Python 依赖
- `.github/workflows/daily_run.yml`：GitHub Actions 定时任务配置
- `pushed_history.json`：已推送项目记录（自动更新）

## 消息格式示例

机器人现在使用 Telegram HTML 模式发送，大致结构如下：

```
🚀 <b>owner/repo</b>
一句话核心亮点总结

🏷 标签：#Python #开源推荐 #GitHub热门

⭐ Star 数：1234

🟢 <b>项目介绍：</b>
- 核心突破：...
- 关键优势：...
- 适用场景：...

🖥 <a href="https://github.com/...">点击查看项目源码</a>

<b>野火 @YeHuoShare</b>
```

## 注意事项

- GitHub Models 免费额度有限，请合理使用
- 确保 `GH_TOKEN` 拥有 `models:read` 权限
- 首次运行会推送符合条件的项目，之后根据历史去重
- 当前实现是「近期创建 + 高 Star」搜索，并非官方 Trending 页面（官方无稳定公开 API）
