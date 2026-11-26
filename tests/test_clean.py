import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from clean import clean, text_features  # noqa: E402


def make_post(**overrides):
    base = {
        "post_id": "1", "author": "zuck", "posted_at": "2026-11-20T16:30:00+00:00",
        "text": "hello", "likes": 10, "replies": 0, "reposts": 1, "quotes": 0,
        "url": "https://www.threads.com/@zuck/post/1", "source": "scraped",
    }
    base.update(overrides)
    return base


class TestDedupe(unittest.TestCase):
    def test_duplicate_keeps_complete_version(self):
        empty = make_post(text="", likes=0, posted_at="")
        full = make_post(text="真正的內容", likes=500)
        other = make_post(post_id="2")
        result, report = clean([empty, full, other])
        self.assertEqual(len(result), 2)
        self.assertEqual(report["duplicates_removed"], 1)
        kept = next(r for r in result if r["post_id"] == "1")
        self.assertEqual(kept["text"], "真正的內容")
        self.assertEqual(kept["likes"], 500)


class TestEmptyShell(unittest.TestCase):
    def test_empty_shell_records_are_removed(self):
        # 實際資料中發現的情況：有 post_id 但沒有文字、時間、互動數
        shell = make_post(post_id="9", text="", posted_at="", likes=0, reposts=0)
        result, report = clean([make_post(), shell])
        self.assertEqual([r["post_id"] for r in result], ["1"])
        self.assertEqual(report["empty_shells_removed"], 1)


class TestFillMissing(unittest.TestCase):
    def test_missing_fields_get_defaults_and_are_counted(self):
        p = make_post()
        del p["likes"]
        p["text"] = None
        del p["source"]
        result, report = clean([p])
        r = result[0]
        self.assertEqual(r["likes"], 0)
        self.assertEqual(r["text"], "")
        self.assertEqual(r["source"], "unknown")
        self.assertEqual(report["filled_fields"], {"likes": 1, "text": 1, "source": 1})
        self.assertEqual(report["filled_records_total"], 3)


class TestTimezone(unittest.TestCase):
    def test_utc_converted_to_taipei_crossing_midnight(self):
        # UTC 週五 16:30 → 台北 週六 00:30（跨日，最容易出錯的情況）
        result, _ = clean([make_post(posted_at="2026-11-20T16:30:00+00:00")])
        r = result[0]
        self.assertEqual(r["posted_at_local"], "2026-11-21T00:30:00+08:00")
        self.assertEqual(r["hour"], 0)
        self.assertEqual(r["weekday"], 5)  # 週六

    def test_bad_timestamp_does_not_crash(self):
        result, report = clean([make_post(posted_at="not-a-date")])
        self.assertIsNone(result[0]["hour"])
        self.assertEqual(report["unparsable_posted_at"], 1)


class TestTextFeatures(unittest.TestCase):
    def test_counts_ignore_url_anchor_and_email(self):
        f = text_features("今天 #工程師日常 #debug 找 @zuck 聊 https://a.com/#x 寫信 me@mail.com")
        self.assertEqual(f["hashtag_count"], 2)
        self.assertEqual(f["mention_count"], 1)
        self.assertEqual(f["url_count"], 1)


if __name__ == "__main__":
    unittest.main()
