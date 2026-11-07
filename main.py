import os
import json
import time
import base64
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


def get_repo_readme(full_name: str, token: str) -> str:
    """获取仓库 README 内容的前 1500 个字符"""
    url = f"https://api.github.com/repos/{full_name}/readme"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            content_b64 = resp.json().get("content", "")
            readme_text = base64.b64decode(content_b64).decode("utf-8", errors="ignore")
            return readme_text[:1500]
    except Exception as e:
        print(f"[Warn] 获取 README 失败 ({full_name}): {e}")
    return ""


def generate_telegram_message(repo: dict, readme_snippet: str, client: OpenAI) -> str:
    """使用 GitHub Models 按全中文排版生成 Telegram 文案"""
    name = repo.get("full_name", "")
    html_url = repo.get("html_url", "")
    description = repo.get("description") or "暂无详细描述"
    stars = repo.get("stargazers_count", 0)
    language = repo.get("language") or "Unknown"

    prompt = f"""你是一位专业的中文开源技术编辑。请阅读提供的 GitHub 项目英文信息，并将其【完全重构并翻译为地道的中文】 Telegram 推荐文案。

严禁照抄英文原文！正文介绍部分绝对不要出现英文截断符号（...），绝对不能包含 `>` 引用符号。

【输出标准排版】：

🚀 **{name}**
用一句话中文总结这个项目最核心的亮点

🏷 标签：#{language} #开源推荐 #GitHub热门

⭐ Star 数：{stars}

🟢 **项目介绍：**
- 详细介绍点 1（必须全部为高质量中文，介绍具体功能）
- 详细介绍点 2（必须全部为高质量中文，介绍适用场景）
- 详细介绍点 3（必须全部为高质量中文，介绍技术优势）

🖥 [点击查看项目源码]({html_url})

**野火 @YeHuoShare**

---
【参考原始信息】：
- 项目名称：{name}
- 编程语言：{language}
- Star 数：{stars}
- 官方描述（英文）：{description}
- README 核心摘要片段：
{readme_snippet if readme_snippet else "无额外 README"}

请直接输出排版好的中文文案（不要有任何前言或总结话术）："""

    try:
        response = client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "你是一位优秀的开源项目中文推荐编辑。你唯一的任务是输出纯中文润色的文案，绝不使用 > 符号，绝不复制英文原句。"
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=600
        )

        content = None
        if hasattr(response, "choices") and response.choices:
            choice = response.choices[0]
            msg = getattr(choice, "message", None)
            if msg is not None:
                content = getattr(msg, "content", None)

        if content and isinstance(content, str):
            content = content.strip().replace("> ", "").replace(">", "")
            print("[Info] AI 生成中文文案成功！")
            return content

    except Exception as e:
        print(f"[Error] AI 生成文案失败: {e}")

    # 保底输出逻辑（也做中文处理）
    return (
        f"🚀 **{name}**\n"
        f"近期热门开源项目推荐\n\n"
        f"🏷 标签：#{language} #开源推荐 #GitHub\n\n"
        f"⭐ Star 数：{stars}\n\n"
        f"🟢 **项目介绍：**\n"
        f"- 该项目目前拥有较高关注度，主语言为 {language}。\n"
        f"- 官方描述：{description}\n\n"
        f"🖥 [点击查看项目源码]({html_url})\n\n"
        f"**野火 @YeHuoShare**"
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

        # 1. 抓取 README 文本
        readme_snippet = get_repo_readme(full_name, GH_TOKEN)

        # 2. 生成中文 AI 文案
        message = generate_telegram_message(repo, readme_snippet, client)
        print("生成文案预览:\n", message[:300], "...")

        # 3. 推送到 Telegram
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
