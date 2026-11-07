import os
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from openai import OpenAI

# ==================== 配置 ====================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
GH_TOKEN = os.getenv("GH_TOKEN")

HISTORY_FILE = Path("pushed_history.json")
MAX_PUSH_PER_RUN = 2
MIN_STARS = 50
DAYS_AGO = 30

# ==================== 工具函数 ====================
def load_history() -> set:
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("pushed_ids", []))
        except Exception:
            return set()
    return set()


def save_history(pushed_ids: set):
    data = {
        "pushed_ids": sorted(list(pushed_ids)),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_github_trending_repos(token: str, days: int = 30, min_stars: int = 50) -> list:
    """抓取近期创建且星数较高的开源项目"""
    since_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    # 搜索：近 N 天创建、星数 >= min_stars、按星数排序
    query = f"created:>{since_date} stars:>={min_stars}"
    url = "https://api.github.com/search/repositories"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    params = {
        "q": query,
        "sort": "stars",
        "order": "desc",
        "per_page": 30
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("items", [])
    except Exception as e:
        print(f"[Error] GitHub API 请求失败: {e}")
        return []


def generate_telegram_message(repo: dict, client: OpenAI) -> str:
    """使用 GitHub Models (gpt-4o-mini) 生成精美 Telegram 文案"""
    name = repo.get("full_name", "")
    html_url = repo.get("html_url", "")
    description = repo.get("description") or "暂无描述"
    stars = repo.get("stargazers_count", 0)
    language = repo.get("language") or "Unknown"
    created_at = repo.get("created_at", "")[:10]

    prompt = f"""你是一位专业的开源项目推荐编辑。请根据以下 GitHub 项目信息，撰写一篇结构精美、排版优雅、适合 Telegram 频道的推荐文案。

项目信息：
- 名称：{name}
- 链接：{html_url}
- Star 数：{stars}
- 主要语言：{language}
- 创建时间：{created_at}
- 描述：{description}

要求：
1. 使用 Markdown 格式（Telegram 支持的部分）
2. 包含醒目标题（带 Emoji）
3. 一句话精炼介绍
4. 3 个核心亮点（每条前面加合适的 Emoji）
5. 在文末给出项目链接和几个相关标签（#标签）
6. 整体风格专业、简洁、有吸引力，控制在 300 字以内
7. 不要输出任何多余的说明文字，直接输出最终文案

请直接输出最终 Markdown 文案："""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "你是一位专业的开源项目推荐编辑，擅长撰写精美、有吸引力的 Telegram 频道文案。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=600
        )
        content = response.choices[0].message.content.strip()
        return content
    except Exception as e:
        print(f"[Error] AI 生成文案失败: {e}")
        # 降级方案
        return (
            f"🚀 **{name}**\n\n"
            f"{description}\n\n"
            f"⭐ Stars: {stars} | 💻 Language: {language}\n\n"
            f"🔗 {html_url}\n\n"
            f"#OpenSource #{language}"
        )


def send_telegram_message(token: str, chat_id: str, text: str) -> bool:
    """通过 Telegram Bot API 发送 Markdown 消息"""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    try:
        resp = requests.post(url, json=payload, timeout=20)
        if resp.status_code == 200:
            print("[Success] 消息已推送到 Telegram")
            return True
        else:
            print(f"[Error] Telegram 发送失败: {resp.status_code} - {resp.text}")
            # 如果 Markdown 解析失败，尝试纯文本
            payload["parse_mode"] = None
            resp2 = requests.post(url, json=payload, timeout=20)
            if resp2.status_code == 200:
                print("[Success] 以纯文本模式重新发送成功")
                return True
            return False
    except Exception as e:
        print(f"[Error] Telegram 请求异常: {e}")
        return False


# ==================== 主逻辑 ====================
def main():
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, GH_TOKEN]):
        print("[Error] 缺少必要环境变量：TELEGRAM_BOT_TOKEN / TELEGRAM_CHANNEL_ID / GH_TOKEN")
        return

    print("=== GitHub 热门开源项目推送机器人 开始运行 ===")
    print(f"时间: {datetime.now(timezone.utc).isoformat()}")

    # 初始化 OpenAI 客户端（指向 GitHub Models）
    client = OpenAI(
        base_url="https://models.github.ai/inference",
        api_key=GH_TOKEN
    )

    # 加载历史记录
    pushed_ids = load_history()
    print(f"已推送历史项目数: {len(pushed_ids)}")

    # 获取候选仓库
    repos = get_github_trending_repos(GH_TOKEN, days=DAYS_AGO, min_stars=MIN_STARS)
    print(f"获取到候选仓库数: {len(repos)}")

    pushed_count = 0
    for repo in repos:
        if pushed_count >= MAX_PUSH_PER_RUN:
            break

        repo_id = str(repo.get("id"))
        if not repo_id or repo_id in pushed_ids:
            continue

        full_name = repo.get("full_name", "unknown")
        print(f"\n正在处理: {full_name} (⭐ {repo.get('stargazers_count', 0)})")

        # 生成文案
        message = generate_telegram_message(repo, client)
        print("生成文案预览:\n", message[:200], "...")

        # 推送
        success = send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, message)
        if success:
            pushed_ids.add(repo_id)
            pushed_count += 1
            # 稍作间隔，避免过快
            time.sleep(2)
        else:
            print(f"跳过推送失败的项目: {full_name}")

    # 保存历史
    save_history(pushed_ids)
    print(f"\n本次成功推送 {pushed_count} 个项目")
    print("=== 运行结束 ===")


if __name__ == "__main__":
    main()
