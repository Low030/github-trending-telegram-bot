import os
import json
import time
import html
import base64
import traceback
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from openai import OpenAI

# ==================== 配置 ====================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
GH_TOKEN = os.getenv("GH_TOKEN")
# 个人/频道品牌签名，从 Secrets 读取；为空则不追加
BRAND_SIGNATURE = (os.getenv("BRAND_SIGNATURE") or "").strip()

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
        except Exception as e:
            print(f"[Warn] 读取历史记录失败: {e}")
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
    """抓取近期创建且星数较高的开源项目（排除 fork）"""
    since_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    query = f"created:>{since_date} stars:>={min_stars} fork:false"
    url = "https://api.github.com/search/repositories"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github-trending-telegram-bot"
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
    """获取仓库 README 内容的前 2000 个字符，辅助 AI 抓取技术深度"""
    url = f"https://api.github.com/repos/{full_name}/readme"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github-trending-telegram-bot"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            content_b64 = resp.json().get("content", "")
            readme_text = base64.b64decode(content_b64).decode("utf-8", errors="ignore")
            return readme_text[:2000]
    except Exception as e:
        print(f"[Warn] 获取 README 失败 ({full_name}): {e}")
    return ""


def append_brand_signature(message: str) -> str:
    """若配置了 BRAND_SIGNATURE，则在文案末尾追加签名（HTML 安全）"""
    if not BRAND_SIGNATURE:
        return message
    # 允许签名里写简单 HTML（如 <b>），其余文本转义由用户自行控制；
    # 这里只做最小处理：去掉首尾空白并保证与正文有空行分隔
    sig = BRAND_SIGNATURE.strip()
    if not sig:
        return message
    return f"{message.rstrip()}\n\n{sig}"


def generate_telegram_message(repo: dict, readme_snippet: str, client: OpenAI) -> str:
    """使用 GitHub Models 生成深度硬核技术中文推荐文案（HTML 格式）"""
    name = repo.get("full_name", "") or "unknown"
    html_url = repo.get("html_url", "") or ""
    description = repo.get("description") or "暂无详细描述"
    stars = repo.get("stargazers_count", 0)
    language = repo.get("language") or "Unknown"

    safe_name = html.escape(name)
    safe_url = html.escape(html_url)
    safe_lang = html.escape(str(language))
    safe_stars = html.escape(str(stars))

    prompt = f"""你是一位极具专业洞察力的开源技术记者。请阅读提供的 GitHub 项目英文资料，深入提炼其【核心技术突破、底层原理与核心亮点】，用流畅地道的中文重新撰写 Telegram 推荐文案。

【严禁规则】：
1. 绝对禁止照抄英文原文，绝对禁止使用英文截断符（...）。
2. 绝对不能输出空洞套话（例如“该项目拥有较高关注度”、“值得关注”等废话）。
3. 必须提炼出实质技术点：例如是“原生重构而非模拟器”、“利用物理架构优化”、“大幅提升帧率/渲染效率”等硬核核心。
4. 绝对不要使用 Markdown 语法（禁止 **、*、[]()、` 等）。
5. 只能使用 Telegram HTML 标签：<b>、<i>、<a href="...">、<code>。不要使用其他标签。
6. 正文中的 < 和 > 如果不是标签，请写成 < 和 >。
7. 不要添加任何个人签名、品牌名、频道名或推广信息。

【固定输出格式】（请严格按此结构输出，不要增加或删除段落标题）：

🚀 <b>{safe_name}</b>
用一句话中文炸裂总结该项目的核心黑科技与本质突破

🏷 标签：#{safe_lang} #开源推荐 #GitHub热门

⭐ Star 数：{safe_stars}

🟢 <b>项目介绍：</b>
- 核心突破：精准说明项目原理与底层技术创新。
- 关键优势：性能、画质或效率的具体提升效果。
- 适用场景：支持的设备环境或使用方式。

🖥 <a href="{safe_url}">点击查看项目源码</a>

---
【项目原始资料】：
- 项目完整名称：{name}
- 主要语言：{language}
- Star 数：{stars}
- 官方描述：{description}
- README 核心片段：
{readme_snippet if readme_snippet else "无"}

请直接输出排版好的中文 HTML 文案（不要包含任何思考过程或开场白）："""

    try:
        response = client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一位优秀的硬核开源技术编辑。"
                        "你唯一的任务是输出高质量中文技术提炼文案。"
                        "必须使用 Telegram HTML 格式（<b>、<a href=\"...\"> 等），"
                        "绝不能使用 Markdown，绝不包含通用废话，不要添加任何签名或品牌。"
                    )
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=700
        )

        content = None
        if hasattr(response, "choices") and response.choices:
            choice = response.choices[0]
            msg = getattr(choice, "message", None)
            if msg is not None:
                content = getattr(msg, "content", None)

        if content and isinstance(content, str):
            content = content.strip()
            content = content.replace("**", "").replace("__", "")
            print(f"[Info] AI 成功为 {name} 生成深度中文 HTML 文案！")
            return append_brand_signature(content)

    except Exception as e:
        print(f"[Error] AI 生成文案发生异常: {e}")
        traceback.print_exc()

    # 安全保底输出（纯 HTML，动态内容已转义）
    safe_desc = html.escape(description)
    fallback = (
        f"🚀 <b>{safe_name}</b>\n"
        f"热门 GitHub 开源技术项目\n\n"
        f"🏷 标签：#{safe_lang} #开源推荐 #GitHub\n\n"
        f"⭐ Star 数：{safe_stars}\n\n"
        f"🟢 <b>项目介绍：</b>\n"
        f"- 关键功能：{safe_desc}\n"
        f"- 主要开发语言：{safe_lang}\n\n"
        f"🖥 <a href=\"{safe_url}\">点击查看项目源码</a>"
    )
    return append_brand_signature(fallback)


def send_telegram_message(token: str, chat_id: str, text: str) -> bool:
    """通过 Telegram Bot API 发送 HTML 消息，失败时降级为纯文本"""
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    payload_html = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    try:
        resp = requests.post(url, json=payload_html, timeout=20)
        if resp.status_code == 200:
            print("[Success] 消息已成功推送到 Telegram (HTML 模式)")
            return True

        print(f"[Warn] Telegram HTML 发送失败 ({resp.status_code}): {resp.text}")

        plain = text
        for tag in ("b", "strong", "i", "em", "u", "s", "code", "pre"):
            plain = plain.replace(f"<{tag}>", "").replace(f"</{tag}>", "")
        plain = re.sub(r'<a\s+href="[^"]*">([^<]*)</a>', r"\1", plain, flags=re.IGNORECASE)
        plain = plain.replace("<", "<").replace(">", ">").replace("&", "&")

        payload_plain = {
            "chat_id": chat_id,
            "text": plain,
            "disable_web_page_preview": False
        }
        resp_plain = requests.post(url, json=payload_plain, timeout=20)
        if resp_plain.status_code == 200:
            print("[Success] 消息以纯文本模式重新发送成功")
            return True

        print(f"[Error] 纯文本模式发送也失败: {resp_plain.text}")
        return False

    except Exception as e:
        print(f"[Error] Telegram 请求发送异常: {e}")
        traceback.print_exc()
        return False


# ==================== 主逻辑 ====================
def main():
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, GH_TOKEN]):
        print("[Error] 缺少必要环境变量：TELEGRAM_BOT_TOKEN / TELEGRAM_CHANNEL_ID / GH_TOKEN")
        return

    print("=== GitHub 热门开源项目推送机器人 开始运行 ===")
    print(f"时间: {datetime.now(timezone.utc).isoformat()}")
    if BRAND_SIGNATURE:
        print("[Info] 已加载品牌签名（来自 BRAND_SIGNATURE Secret）")
    else:
        print("[Info] 未配置 BRAND_SIGNATURE，消息末尾不追加签名")

    try:
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
            print(f"\n正在处理项目: {full_name} (⭐ {repo.get('stargazers_count', 0)})")

            readme_snippet = get_repo_readme(full_name, GH_TOKEN)
            message = generate_telegram_message(repo, readme_snippet, client)
            print("--- 文案生成预览 ---")
            print(message)
            print("-------------------")

            success = send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, message)
            if success:
                pushed_ids.add(repo_id)
                pushed_count += 1
                time.sleep(2)
            else:
                print(f"[Skip] 发送失败，跳过记录: {full_name}")

        save_history(pushed_ids)
        print(f"\n本次成功推送 {pushed_count} 个项目")
        print("=== 运行结束 ===")

    except Exception as e:
        print(f"[Fatal Error] 主程序运行异常: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
