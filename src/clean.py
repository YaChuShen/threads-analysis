"""
Checkpoint 3: 資料清理

輸入: data/posts.json（scraper.py 的輸出）
輸出: data/posts_clean.json（清理後貼文）+ data/clean_report.json（清理統計）

假設（詳見 README / AI_LOG）:
- hashtag: `#` 後接中英文、數字或底線，且 `#` 前面不能緊貼文字（避免 C#、網址 #anchor 被算進去）
- mention: `@` 後接英數、底線、句點（Threads 帳號規則），且 `@` 前面不能緊貼文字（排除 email）
- url: http:// 或 https:// 或 www. 開頭，直到空白為止
- text_length: 去頭尾空白後的 Unicode 字元數，中文一字算 1，英文一個字母算 1
- 去重: 同一個 post_id 保留「較完整」的那筆（有文字 / 有讚數 / 有時間），一樣完整就保留先出現的
- weekday: 0=週一 ... 6=週日（Python 慣例）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Taipei")

NUMERIC_FIELDS = ["likes", "replies", "reposts", "quotes"]
TEXT_FIELDS = ["post_id", "author", "posted_at", "text", "url"]
DEFAULT_SOURCE = "unknown"

URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
HASHTAG_RE = re.compile(r"(?<![\w#])#([\w一-鿿]+)")
MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_.]+)")


def _completeness(p: dict) -> int:
    return sum([bool(p.get("text")), (p.get("likes") or 0) > 0, bool(p.get("posted_at"))])


def dedupe(posts: list[dict]) -> tuple[list[dict], int]:
    """依 post_id 去重，回傳 (去重後清單, 被移除的筆數)。沒有 post_id 的資料直接丟掉並計入移除。"""
    by_id: dict[str, dict] = {}
    removed = 0
    for p in posts:
        pid = p.get("post_id")
        if not pid:
            removed += 1
            continue
        pid = str(pid)
        if pid not in by_id:
            by_id[pid] = p
        else:
            removed += 1
            if _completeness(p) > _completeness(by_id[pid]):
                by_id[pid] = p
    return list(by_id.values()), removed


def fill_missing(post: dict, fill_counts: dict[str, int]) -> dict:
    """補缺漏欄位：數字補 0、文字補空字串、source 補 unknown。fill_counts 會被就地累加。"""
    out = dict(post)
    for f in NUMERIC_FIELDS:
        v = out.get(f)
        try:
            out[f] = int(v)  # None 會丟 TypeError，"abc" 會丟 ValueError，"12" 會轉成 12
        except (TypeError, ValueError):
            out[f] = 0
            fill_counts[f] = fill_counts.get(f, 0) + 1
    for f in TEXT_FIELDS:
        v = out.get(f)
        if not isinstance(v, str):
            out[f] = "" if v is None else str(v)
            if v is None:
                fill_counts[f] = fill_counts.get(f, 0) + 1
    if not out.get("source"):
        out["source"] = DEFAULT_SOURCE
        fill_counts["source"] = fill_counts.get("source", 0) + 1
    return out


def to_taipei(posted_at: str) -> dict:
    """UTC ISO8601 → 台北時間。無法解析時三個欄位都回傳 None，不讓整批失敗。"""
    if not posted_at:
        return {"posted_at_local": None, "hour": None, "weekday": None}
    try:
        dt = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
    except ValueError:
        return {"posted_at_local": None, "hour": None, "weekday": None}
    if dt.tzinfo is None:  # 沒時區資訊就當作 UTC（scraper 輸出就是 UTC）
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    local = dt.astimezone(TZ)
    return {"posted_at_local": local.isoformat(), "hour": local.hour, "weekday": local.weekday()}


def text_features(text: str) -> dict:
    urls = URL_RE.findall(text)
    text_no_url = URL_RE.sub(" ", text)  # 先拿掉網址，避免網址裡的 # 或 @ 被誤算
    return {
        "text_length": len(text.strip()),
        "hashtag_count": len(HASHTAG_RE.findall(text_no_url)),
        "mention_count": len(MENTION_RE.findall(text_no_url)),
        "url_count": len(urls),
    }


def is_empty_shell(p: dict) -> bool:
    """沒有文字、沒有時間、所有互動數都是 0 的資料。
    實測發現爬蟲會抓到這種節點（post_id 和真實貼文前綴相同，推測是多圖貼文裡的子項目），
    它們不是獨立貼文，留著會拉低平均值，所以直接移除。"""
    return (
        not (p.get("text") or "").strip()
        and not p.get("posted_at")
        and all(not p.get(f) for f in NUMERIC_FIELDS)
    )


def clean(posts: list[dict]) -> tuple[list[dict], dict]:
    deduped, dup_removed = dedupe(posts)
    fill_counts: dict[str, int] = {}
    unparsable_time = 0
    empty_removed = 0
    result = []
    for p in deduped:
        if is_empty_shell(p):
            empty_removed += 1
            continue
        c = fill_missing(p, fill_counts)
        t = to_taipei(c["posted_at"])
        if c["posted_at"] and t["hour"] is None:
            unparsable_time += 1
        c.update(t)
        c.update(text_features(c["text"]))
        result.append(c)
    report = {
        "input_count": len(posts),
        "output_count": len(result),
        "duplicates_removed": dup_removed,
        "empty_shells_removed": empty_removed,
        "filled_fields": fill_counts,
        "filled_records_total": sum(fill_counts.values()),
        "unparsable_posted_at": unparsable_time,
        "by_source": {s: sum(1 for r in result if r["source"] == s) for s in sorted({r["source"] for r in result})},
    }
    return result, report


def main() -> None:
    ap = argparse.ArgumentParser(description="清理 Threads 貼文資料")
    ap.add_argument("--in", dest="inp", default="data/posts.json")
    ap.add_argument("--out", default="data/posts_clean.json")
    ap.add_argument("--report", default="data/clean_report.json")
    args = ap.parse_args()

    posts = json.loads(Path(args.inp).read_text(encoding="utf-8"))
    cleaned, report = clean(posts)
    Path(args.out).write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)


if __name__ == "__main__":
    main()
