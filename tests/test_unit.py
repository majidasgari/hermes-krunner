#!/usr/bin/env python3
"""Unit tests for hermes-krunner (stdlib only: python3 -m unittest discover tests)."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("hermes_krunner", ROOT / "hermes-krunner.py")
hk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hk)

TRIGGERS = hk.DEFAULTS["triggers"]


class TestTriggers(unittest.TestCase):
    def test_punctuation_trigger_glued_to_text(self):
        self.assertEqual(hk.strip_trigger("?پایتخت استرالیا", TRIGGERS), (True, "پایتخت استرالیا"))
        self.assertEqual(hk.strip_trigger("? پایتخت استرالیا", TRIGGERS), (True, "پایتخت استرالیا"))

    def test_persian_and_english_triggers(self):
        expected = {"هرمس سلام": "سلام", "hermes hello": "hello", "HERMES hello": "hello",
                    "آنا سلام": "سلام", "ana hi": "hi", "کتی سلام": "سلام", "kattie hi": "hi"}
        for query, want in expected.items():
            is_ask, question = hk.strip_trigger(query, TRIGGERS)
            self.assertTrue(is_ask, query)
            self.assertEqual(question, want, query)

    def test_arabic_variants(self):
        self.assertEqual(hk.strip_trigger("هرمس سلام", TRIGGERS)[0], True)
        self.assertEqual(hk.strip_trigger("hermes:سلام", TRIGGERS), (True, "سلام"))

    def test_non_trigger_queries_are_ignored(self):
        for query in ("firefox", "kate", "پایتخت استرالیا", "", "   ", "hermesx foo", "ananas"):
            self.assertEqual(hk.strip_trigger(query, TRIGGERS)[0], False, query)

    def test_trigger_only_is_hint(self):
        self.assertEqual(hk.strip_trigger("?", TRIGGERS), (True, ""))
        self.assertEqual(hk.strip_trigger("هرمس", TRIGGERS), (True, ""))

    def test_normalize_folds_variants(self):
        self.assertEqual(hk.normalize_text("علي"), hk.normalize_text("علی"))
        self.assertEqual(hk.normalize_text("كيف"), hk.normalize_text("کیف"))
        self.assertEqual(hk.normalize_text("  چند   کلمه\u200cای "), "چند کلمه ای")

    def test_question_key_is_stable(self):
        self.assertEqual(hk.question_key("  سلام!  "), hk.question_key("سلام!"))
        self.assertEqual(hk.question_key("علي"), hk.question_key("علی"))


class TestAnswerFormatting(unittest.TestCase):
    def test_clip(self):
        self.assertEqual(hk.clip_answer("abc", 10), "abc")
        self.assertTrue(hk.clip_answer("x" * 50, 10).startswith("x" * 10))
        self.assertTrue(hk.clip_answer("x" * 50, 10).endswith("…"))

    def test_inline_text_escapes_html_and_keeps_bold(self):
        out = hk.inline_text("**bold** and <script>\nplain")
        self.assertIn("<b>bold</b>", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertNotIn("<script>", out)
        self.assertIn("<br>", out)

    def test_inline_text_caps_line_count(self):
        out = hk.inline_text("\n".join(f"line {i}" for i in range(200)))
        self.assertLessEqual(out.count("<br>"), 41)

    def test_clean_cli_output_strips_box_drawing(self):
        raw = "Query: x\nInitializing agent...\n╭─ Hermes ─╮\n۲\n╰─────────╯\nResume: hermes --resume x\n"
        out = hk.clean_cli_output(raw)
        self.assertIn("۲", out)
        self.assertNotIn("╭", out)
        self.assertNotIn("─────────", out)


class TestCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "answers.json"
        self.cache = hk.AnswerCache(self.path, 3)

    def tearDown(self):
        self.tmp.cleanup()

    def test_put_get_roundtrip_survives_reload(self):
        self.cache.put("پایتخت استرالیا؟", "کانبرا", engine="app", session="20260101_x")
        self.assertIsNone(self.cache.get("نامربوط"))
        hit = self.cache.get("پایتخت استرالیا ؟")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["a"], "کانبرا")
        reloaded = hk.AnswerCache(self.path, 3)
        self.assertEqual(reloaded.get("پایتخت استرالیا؟")["a"], "کانبرا")

    def test_size_is_capped_and_newest_first(self):
        for i in range(5):
            self.cache.put(f"q{i}", f"a{i}")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(data["entries"]), 3)
        self.assertEqual(data["entries"][0]["a"], "a4")

    def test_empty_answer_is_not_cached(self):
        self.cache.put("q", "")
        self.assertIsNone(self.cache.get("q"))


class TestMatchBuilding(unittest.TestCase):
    def test_match_tuple_shape(self):
        m = hk.build_match("ask::x", "text", subtext="sub", multiline=True, actions=["open"])
        mid, text, icon, cat, rel, props = m
        self.assertEqual(mid, "ask::x")
        self.assertEqual(text, "text")
        self.assertIsInstance(cat, int)
        self.assertIsInstance(rel, float)
        self.assertEqual(props["subtext"], "sub")
        self.assertTrue(props["multiline"])
        self.assertEqual(props["actions"], ["open"])
        self.assertEqual(props["category"], "هرمس")

    def test_default_actions_are_defined(self):
        ids = [a[0] for a in hk.ACTIONS]
        self.assertEqual(ids, ["open", "reask", "new"])
        # Enter (no action id) opens Hermes; "open" must be the primary action.
        self.assertEqual(hk.ACTIONS[0][0], hk.ACTION_OPEN)


class TestClassifyQuery(unittest.TestCase):
    """Any query must surface Hermes: triggered ones ask, plain ones suggest."""

    def setUp(self):
        self.cfg = dict(hk.DEFAULTS)

    def mode(self, query, **over):
        cfg = dict(self.cfg)
        cfg.update(over)
        return hk.classify_query(cfg, query)

    def test_plain_query_suggests(self):
        d = self.mode("پایتخت استرالیا کجاست")
        self.assertEqual(d["mode"], "suggest")
        self.assertEqual(d["question"], "پایتخت استرالیا کجاست")

    def test_question_mark_asks_without_trigger(self):
        """«… چی بود؟» is the user signalling "send it" — no Enter needed."""
        for q in ("شماره کارت من چی بود؟", "what is the capital of Australia?"):
            self.assertEqual(self.mode(q)["mode"], "ask", q)

    def test_question_mark_can_be_disabled(self):
        d = self.mode("شماره کارت من چی بود؟", auto_ask_on_question_mark=False)
        self.assertEqual(d["mode"], "suggest")

    def test_typing_never_asks(self):
        """Prefixes of a question must stay silent — only the finished text asks."""
        for q in ("شماره", "شماره کارت", "شماره کارت من", "شماره کارت من چی بود"):
            self.assertEqual(self.mode(q)["mode"], "suggest", q)

    def test_plain_query_can_be_silenced(self):
        self.assertEqual(self.mode("پایتخت استرالیا", suggest_untriggered=False)["mode"], "ignore")

    def test_triggered_query_asks(self):
        for q in ("? پایتخت استرالیا کجاست؟", "؟ پایتخت استرالیا", "hermes: hello there", "هرمس سلام"):
            self.assertEqual(self.mode(q)["mode"], "ask", q)

    def test_triggered_query_without_auto_ask_is_manual(self):
        self.assertEqual(self.mode("? پایتخت استرالیا کجاست", auto_ask=False)["mode"], "manual")

    def test_lone_trigger_hints(self):
        self.assertEqual(self.mode("?")["mode"], "hint")
        self.assertEqual(self.mode("?  ")["mode"], "hint")

    def test_tiny_plain_query_is_ignored(self):
        self.assertEqual(self.mode("ab")["mode"], "ignore")

    def test_empty_query_is_ignored(self):
        self.assertEqual(self.mode("")["mode"], "ignore")


class TestFailureTexts(unittest.TestCase):
    """Engine failure prose must never be cached or notified as an answer."""

    def test_detects_cancelled_turn(self):
        self.assertTrue(hk.looks_like_failure("⚠️ No reply: the request was cancelled by a new correction"))
        self.assertTrue(hk.looks_like_failure("Stopped waiting for another Hermes process on this session."))
        self.assertTrue(hk.looks_like_failure(""))

    def test_real_answers_pass(self):
        self.assertFalse(hk.looks_like_failure("کانبرا"))
        self.assertFalse(hk.looks_like_failure("پایتخت استرالیا کانبرا است.\n\nاگر بخواهی می‌توانم بیشتر توضیح بدهم."))


class TestPortDiscovery(unittest.TestCase):
    def test_find_serve_port_returns_int_or_none(self):
        port = hk.find_serve_port()
        self.assertTrue(port is None or isinstance(port, int))
        if port:
            self.assertGreater(port, 1024)

    def test_hermes_bin_is_executable_path(self):
        cfg = dict(hk.DEFAULTS)
        b = hk.hermes_bin(cfg)
        self.assertTrue(b.endswith("hermes"))


class TestLiveBackend(unittest.TestCase):
    """Opt-in: HERMES_KRUNNER_LIVE=1 python3 -m unittest tests.test_unit"""

    @unittest.skipUnless(os.environ.get("HERMES_KRUNNER_LIVE") == "1", "set HERMES_KRUNNER_LIVE=1")
    def test_ask_through_desktop_backend(self):
        cfg = dict(hk.DEFAULTS)
        cfg["engine"] = "app"
        cfg["launch_app_if_down"] = False
        asker = hk.Asker(cfg)
        self.assertTrue(asker.backend_up(), "desktop backend must be running")
        answer, _ask = asker.answer_now("فقط عدد جواب بده: ۳+۴", timeout=120, force=True)
        self.assertIn("۷", answer)


if __name__ == "__main__":
    unittest.main(verbosity=2)
