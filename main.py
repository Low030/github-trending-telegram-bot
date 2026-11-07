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


def build_fallback_message(repo: dict) -> str:
    """严格按最新指定排版生成降级文案"""
    name = repo.get("full_name", "unknown")
    html_url = repo.get("html_url", "")
    description = (repo.get("description") or "一个值得关注的开源项目").strip()
    stars = repo.get("stargazers_count", 0)
    language = repo.get("language") or "Unknown"

    if len(description) > 120:
        description = description[:117] + "..."

    return (
        f"🚀 **{name}**\n"
        f"近期热门精选开源项目\n\n"
        f"🏷 标签：#{language} #OpenSource #GitHub\n\n"
        f"⭐ Star 数：{stars}\n\n"
        f"🟢 **项目介绍：**\n"
        f"> {description}\n\n"
        f"🖥 [点击查看项目源码]({html_url})\n\n"
        f"**野火 @YeHuoShare**"
    )


def generate_telegram_message(repo: dict, client: OpenAI) -> str:
    """使用 GitHub Models 按指定排版生成 Telegram 文案，失败则使用降级模板"""
    name = repo.get("full_name", "")
    html_url = repo.get("html_url", "")
    description = repo.get("description") or "暂无描述"
    stars = repo.get("stargazers_count", 0)
    language = repo.get("language") or "Unknown"
    created_at = repo.get("created_at", "")[:10]

    prompt = f"""你是一位专业的开源项目推荐编辑。请严格根据以下排版格式，为这个 GitHub 项目生成 Telegram 推荐文案。

【必须严格遵守的排版格式】（请原样输出，不要增减结构）：

🚀 **项目名称**
简短亮点

🏷 标签：#标签1 #标签2 #标签3

⭐ Star 数：数字

🟢 **项目介绍：**
> 用精炼、吸引人的中文分点或段落详细描述项目的核心功能、解决的痛点及适用场景。

🖥 [点击查看项目源码](项目真实链接)

**野火 @YeHuoShare**
---

【项目真实信息】：
- 完整名称：{name}
- 项目地址：{html_url}
- Star 数：{stars}
- 主要语言：{language}
- 创建时间：{created_at}
- 官方描述：{description}

【写作要求】：
1. 第一行：用 🚀 开头，项目名称加粗（**名称**）。第二行写一句吸引人的简短亮点。
2. 🏷标签：后面跟 3 个相关的中文/英文 #标签。
3. ⭐ Star 数：后面跟实际数字 {stars}。
4. 🟢 **项目介绍：** 下方必须使用 Markdown 引用语法 `>`，写 2~4 行高质量的中文介绍。
5. 项目地址行必须写成：🖥 [点击查看项目源码]({html_url})
6. 最后固定写：**野火 @YeHuoShare**
7. 只输出最终文案，不要任何多余说明或开场白。
8. 控制在 350 字以内。

请直接输出最终文案："""

    try:
        response = client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "你是一位专业的开源项目推荐编辑。你必须严格按照用户给出的排版格式输出，绝不添加额外内容，也不要只回复 OK。"
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=500
        )

        content = None
        if hasattr(response, "choices") and response.choices:
            choice = response.choices[0]
            msg = getattr(choice, "message", None)
            if msg is not None:
                content = getattr(msg, "content", None)
            if content is None and isinstance(choice, dict):
                content = choice.get("message", {}).get("content")
        elif isinstance(response, dict):
            content = (
                response.get("choices", [{}])[0]
                .get("message", {})
                .get("content")
            )
        elif isinstance(response, str):
            content = response

        if content and isinstance(content, str):
            content = content.strip()
            if len(content) >= 80 and "OK" != content.upper() and "🚀" in content:
                print("[Info] AI 生成文案成功")
                return content
            else:
                print(f"[Warn] AI 返回内容无效或过短，改用降级模板。内容预览: {content[:50]!r}")
        else:
            print(f"[Warn] AI 返回结构异常，改用降级模板。type={type(response)}")

    except Exception as e:
        print(f"[Error] AI 生成文案失败: {e}")

    return build_fallback_message(repo)


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

    client = OpenAI(
        base_url="https://models.github.ai/inference",
        api_key=GH_TOKEN
    )

    pushed_ids = load_history()
    print(f"已推送历史项目数: {len(pushed_ids)}")

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

        message = generate_telegram_message(repo, client)
        print("生成文案预览:\n", message[:300], "...")

        success = send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, message)
        if success:
            pushed_ids.add(repo_id)
            pushed_count += 1
            time.sleep(2)
        else:
            print(f"跳过推送失败的项目: {full_name}")

    save_history(pushed_ids)
    print(f"\n本次成功推送 {pushed_count} 个项目")
    print("=== 运行结束 ===")


if __name__ == "__main__":
    main()
