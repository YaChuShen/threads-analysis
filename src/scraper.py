"""
Threads 公開帳號貼文爬蟲 — 用 Scrapling 的 StealthyFetcher (基於 Playwright/patchright)

⚠️ 重要說明(請放進 README / AI_LOG.md):
- 這支腳本只抓「公開可見」的頁面內容,不使用登入態、不嘗試繞過登入牆。
- Threads 是重度 JS 渲染的 SPA,頁面資料實際上是內嵌在 <script type="application/json">
  的 JSON blob 裡 (Meta 系產品常見做法,類似 Instagram/Facebook 的 "early data" 注入),
  而不是乾淨的 DOM 結構。所以這支腳本採取「先抓渲染後的 HTML → 嘗試從內嵌 JSON 撈欄位 →
  退回用可見文字 DOM 解析」的三層策略,對應題目要求的「處理爬取限制」。
- 若 Threads 這次改版導致 JSON 結構變了,retry 機制與 fallback 到 mock dataset 的邏輯
  (見 generate_mock_posts) 可以保證整個 pipeline 不會因為爬蟲失敗而整個掛掉。

執行環境需求:
    pip install --break-system-packages "scrapling[fetchers]"
    scrapling install  # 第一次使用需要裝 patchright 的瀏覽器核心

用法:
    python3 threads_scraper.py --username zuck --limit 30
    python3 threads_scraper.py --mock --limit 30   # 網路/爬取失敗時用 mock dataset 繼續跑後面流程
"""

import argparse
import json
import re
import sys
import time
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Post:
    post_id: str
    author: str
    posted_at: str  # ISO8601, UTC
    text: str
    likes: int
    replies: int
    reposts: int
    quotes: int
    url: str
    source: str  # "scraped" or "mock"


def fetch_profile_html(username: str, timeout: int = 20, max_retries: int = 3):
    """用 Scrapling StealthyFetcher 抓渲染後的個人頁 HTML。失敗時 retry + log,
    全部失敗則回傳 None,讓呼叫端 fallback 到 mock dataset。"""
    from scrapling.fetchers import StealthyFetcher

    url = f"https://www.threads.com/@{username}"
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            print(f"[fetch] attempt {attempt}/{max_retries} -> {url}", file=sys.stderr)
            page = StealthyFetcher.fetch(
                url,
                headless=True,
                network_idle=True,   # 等 XHR/JSON 都載完再回傳
                timeout=timeout * 1000,
            )
            if page and page.status == 200:
                return page
            last_err = f"status={getattr(page, 'status', None)}"
        except Exception as e:  # noqa: BLE001 - 爬蟲故意抓寬一點,log 下來就好
            last_err = f"{type(e).__name__}: {e}"
            print(f"[fetch] failed: {last_err}", file=sys.stderr)
        time.sleep(1.5 * attempt)  # 指數退避,降低被判定異常流量的機率

    print(f"[fetch] giving up after {max_retries} attempts, last_err={last_err}", file=sys.stderr)
    return None


def extract_embedded_json(html: str):
    """Threads/Instagram 系頁面常把資料塞進
    <script type="application/json" data-sjs>...</script> 這種標籤裡。
    這裡掃描所有這類 script,嘗試 parse 成 JSON,回傳能 parse 成功的清單。
    (實際欄位路徑需要你實測時打開瀏覽器 devtools 比對,這裡先給掃描框架。)"""
    candidates = []
    for m in re.finditer(
        r'<script[^>]+type="application/json"[^>]*>(.*?)</script>', html, re.S
    ):
        raw = m.group(1).strip()
        try:
            candidates.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return candidates


def parse_posts_from_json_blobs(blobs, username: str, limit: int) -> list[Post]:
    """從 extract_embedded_json 撈出的 JSON 片段裡找出貼文陣列。
    這段需要你用瀏覽器打開 Threads 個人頁、看 Network/Elements 裡
    實際的欄位名稱後再對應修正 —— 下面先用「盡量通用」的 key 嘗試比對,
    找不到就回傳空陣列,讓上層 fallback。"""
    posts_by_id: dict[str, Post] = {}

    def is_complete(p: Post) -> bool:
        # 判斷這筆是不是「完整版」節點:有文字或有讚數才算,
        # 避免被同一篇貼文的精簡/預覽版節點覆蓋掉。
        return bool(p.text) or p.likes > 0 or p.posted_at != ""

    def walk(node):
        if isinstance(node, dict):
            # 2026-11-24 更新:從 Threads 的 Relay GraphQL schema 定義檔裡
            # 實測確認欄位名稱 —— like_count / repost_count / quote_count / taken_at
            # 都猜對了,但 reply 數的真正欄位是 direct_reply_count,不是 reply_count。
            if {"caption", "like_count"} & node.keys() or "text_post_app_info" in node:
                try:
                    pid = str(node.get("pk") or node.get("id") or node.get("code"))
                    if pid and pid != "None":
                        caption = node.get("caption")
                        text = ""
                        if isinstance(caption, dict):
                            text = caption.get("text", "")
                        elif isinstance(caption, str):
                            text = caption
                        candidate = Post(
                            post_id=pid,
                            author=username,
                            posted_at=datetime.fromtimestamp(
                                node.get("taken_at", 0), tz=timezone.utc
                            ).isoformat() if node.get("taken_at") else "",
                            text=text,
                            likes=int(node.get("like_count", 0) or 0),
                            replies=int(node.get("direct_reply_count", 0) or 0),
                            reposts=int(node.get("repost_count", 0) or 0),
                            quotes=int(node.get("quote_count", 0) or 0),
                            url=f"https://www.threads.com/@{username}/post/{pid}",
                            source="scraped",
                        )
                        existing = posts_by_id.get(pid)
                        # 同一個 post_id 只留「比較完整」的那一版,
                        # 不要讓後來出現的空殼節點覆蓋掉已經抓到的完整資料。
                        if existing is None or (is_complete(candidate) and not is_complete(existing)):
                            posts_by_id[pid] = candidate
                except Exception as e:  # noqa: BLE001
                    print(f"[parse] skip malformed node: {e}", file=sys.stderr)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for blob in blobs:
        walk(blob)

    # 依時間新到舊排序(抓不到時間的排最後),再截到 limit 篇
    result = list(posts_by_id.values())
    result.sort(key=lambda p: p.posted_at, reverse=True)
    return result[:limit]


def generate_mock_posts(username: str, n: int) -> list[Post]:
    """Fallback / 測試用的 mock dataset。題目明文允許這條路,
    且要求在 README 說明原因 —— 這裡順便示範欄位要怎麼填滿。"""
    random.seed(42)  # 可重現
    sample_texts = [
        "今天學到一個新的 debug 技巧,分享給大家 #工程師日常",
        "週末去爬山,拍到超美的日出 https://example.com/photo",
        "@someone 這個觀點我同意一半,但...",
        "剛上線的功能大家快去試試看!",
        "純發廢文,沒有重點",
    ]
    posts = []
    now = datetime.now(timezone.utc)
    for i in range(n):
        posts.append(Post(
            post_id=f"mock_{i:03d}",
            author=username,
            posted_at=(now.replace(microsecond=0)).isoformat(),
            text=random.choice(sample_texts),
            likes=random.randint(0, 500),
            replies=random.randint(0, 80),
            reposts=random.randint(0, 40),
            quotes=random.randint(0, 10),
            url=f"https://www.threads.com/@{username}/post/mock_{i:03d}",
            source="mock",
        ))
    return posts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--username", default="zuck")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--mock", action="store_true", help="強制使用 mock dataset,不實際發送請求")
    ap.add_argument("--out", default="posts.json")
    args = ap.parse_args()

    posts: list[Post] = []

    if not args.mock:
        page = fetch_profile_html(args.username)
        if page is not None:
            blobs = extract_embedded_json(page.html_content if hasattr(page, "html_content") else str(page))
            posts = parse_posts_from_json_blobs(blobs, args.username, args.limit)
            print(f"[main] scraped {len(posts)} posts from live page", file=sys.stderr)

    if len(posts) < args.limit:
        need = args.limit - len(posts)
        print(f"[main] falling back to mock dataset for remaining {need} posts "
              f"(scrape returned {len(posts)}/{args.limit})", file=sys.stderr)
        posts.extend(generate_mock_posts(args.username, need))

    out_path = Path(args.out)
    out_path.write_text(
        json.dumps([asdict(p) for p in posts], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[main] wrote {len(posts)} posts -> {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
