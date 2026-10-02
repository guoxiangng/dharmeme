"""The Chinese feature: its voice and themes, both scripts, the Chinese pool, and
drawing Chinese text."""
import io
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PIL import Image

from dharmeme import generator
from dharmeme.catalog import load_catalog
from dharmeme.feedback import Feedback
from dharmeme.limits import Limits
from dharmeme.pool import Pool
from dharmeme.prompt import HANS, MemeError, system_prompt, to_simplified, validate, write_meme
from dharmeme.render import Renderer, fit_text, has_cjk, tokens, wrap
from dharmeme.store import MemoryStore
from dharmeme.telegram import CHINESE, MESSAGES_HANS, MESSAGES_ZH, Bot
from dharmeme.themes import THEMES_DIR, as_topic, load_themes, simplified
from test_bot import FakeTelegram
from test_engine import GOOD, StubLLM

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "templates" / "fonts"
TEMPLATES = load_catalog()
THEMES_ZH = load_themes(THEMES_DIR / "zh.yaml")
THEMES_HANS = simplified(THEMES_ZH)
RENDERER = Renderer(ROOT / "templates" / "images", FONTS / "Anton-Regular.ttf",
                    FONTS / "NotoSansTC.ttf", FONTS / "NotoSansSC.ttf")
GOOD_ZH = {"template_id": "drake", "slots": {"rejected": "專心念佛", "preferred": "邊念邊想晚餐"}}
POOL_ZH = {"id": "z1", "status": "approved", "created": "2026-10-02", "lang": "zh", **GOOD_ZH}
POOL_EN = {"id": "a1", "status": "approved", "created": "2026-10-01", **GOOD}

# Every character one font-size wide: close enough to a square Chinese glyph.
measure = lambda text, size: len(text) * size  # noqa: E731


# --- drawing ---

def test_chinese_breaks_between_characters_and_latin_words_stay_whole():
    assert [t for t, _ in tokens("放下執著")] == ["放", "下", "執", "著"]
    assert tokens("Me 說 OK") == [("Me", False), ("說", True), ("OK", True)]
    assert wrap(measure, "今天一定專心念佛", 10, 40) == ["今天一定", "專心念佛"]


def test_no_line_starts_with_closing_punctuation():
    assert wrap(measure, "念佛，打坐。", 10, 30) == ["念佛，", "打坐。"]
    # Even when only two characters fit, the comma stays with the character before it.
    lines = wrap(measure, "念佛，打坐。", 10, 20)
    assert lines == ["念", "佛，", "打", "坐。"]
    assert not any(line[0] in "，。" for line in lines)


def test_chinese_shrinks_to_fit_and_english_wrapping_is_unchanged():
    fit = fit_text(measure, "嘴上說放下了轉頭又撿回來", 60, 60)
    assert not fit["truncated"] and "".join(fit["lines"]) == "嘴上說放下了轉頭又撿回來"
    assert wrap(lambda t, s: len(t) * s * 0.5, "Letting go of attachment", 40, 200) == [
        "Letting go", "of", "attachment"]


def test_chinese_text_is_drawn_with_a_chinese_font_per_script():
    assert has_cjk("放下") and not has_cjk("Letting go")
    template = next(t for t in TEMPLATES if t["id"] == "drake")
    blank = RENDERER.render(template, {"rejected": " ", "preferred": " "})
    for script in ("tc", "sc"):
        assert RENDERER.render(template, GOOD_ZH["slots"], script) != blank
    # Anton has no Chinese glyphs: it must not be the font measuring Chinese.
    assert RENDERER.font(40, "tc").getlength("放下") != RENDERER.font(40).getlength("放下")
    assert RENDERER.font(40, "sc").path != RENDERER.font(40, "tc").path
    assert Image.open(io.BytesIO(blank)).size == tuple(template["size"])


# --- voice and themes ---

def test_chinese_themes_are_their_own_list():
    assert len(THEMES_ZH) >= 15
    assert all(has_cjk(t["label"]) and has_cjk(t["brief"]) for t in THEMES_ZH)
    assert all(len(f"zh:{t['id']}") <= 64 for t in THEMES_ZH)
    assert {"nianfo", "chisu", "suiyuan"} <= {t["id"] for t in THEMES_ZH}


def test_simplified_is_the_same_content_in_the_other_script():
    assert to_simplified("隨緣、執著、發心、做義工") == "随缘、执著、发心、做义工"
    assert [t["id"] for t in THEMES_HANS] == [t["id"] for t in THEMES_ZH]
    by_id = {t["id"]: t for t in THEMES_HANS}
    assert by_id["suiyuan"]["label"] == "随缘" and by_id["nianfo"]["label"] == "念佛"
    assert by_id["zhigong"]["label"] == "做义工"
    assert all(t["label"] == to_simplified(z["label"]) and t["brief"] == to_simplified(z["brief"])
               for t, z in zip(THEMES_HANS, THEMES_ZH))


def test_each_script_has_its_own_prompt_and_half_the_characters():
    trad, simp = system_prompt(TEMPLATES, "zh"), system_prompt(TEMPLATES, HANS)
    assert "繁體中文" in trad and "漢傳佛教" in trad
    assert "简体中文" in simp and "汉传佛教" in simp and "繁體" not in simp and "繁体" not in simp
    assert "rejected (最多 35 個字)" in trad  # 70 Latin characters -> 35 Chinese ones
    assert "rejected (最多 35 个字)" in simp
    assert validate(GOOD_ZH, TEMPLATES, "zh") == GOOD_ZH
    too_long = {"template_id": "drake", "slots": {"rejected": "字" * 36, "preferred": "好"}}
    for lang in ("zh", HANS):
        with pytest.raises(MemeError):
            validate(too_long, TEMPLATES, lang)
    assert validate(too_long, TEMPLATES)  # the same length is fine in English


def test_simplified_output_never_keeps_a_traditional_character():
    meme = write_meme("念佛", StubLLM(GOOD_ZH), TEMPLATES, HANS)  # the model slipped
    assert meme["slots"] == {"rejected": "专心念佛", "preferred": "边念边想晚餐"}
    assert write_meme("念佛", StubLLM(GOOD_ZH), TEMPLATES, "zh") == GOOD_ZH


def test_chinese_memes_never_use_the_english_only_template():
    class Recorder(StubLLM):
        def complete(self, system, user, max_tokens=None):
            self.systems = getattr(self, "systems", []) + [system]
            return super().complete(system, user, max_tokens)

    llm = Recorder(*[GOOD_ZH] * 40)
    for _ in range(40):
        write_meme("無常", llm, TEMPLATES, "zh")
    assert not any("one-does-not-simply" in s for s in llm.systems)
    assert llm.calls[0] == "主題: 無常"


# --- the bot ---

def make_bot(llm, per_ip=5, pool_memes=(), owner=None):
    store = MemoryStore()
    pool = Pool(store)
    for meme in pool_memes:
        pool.add(meme)
    telegram = FakeTelegram()
    bot = Bot(pool, Limits(store, per_ip=per_ip), lambda: llm, TEMPLATES, RENDERER,
              telegram, owner, Feedback(store), [], THEMES_ZH, THEMES_HANS)
    return bot, telegram, pool


def tap(data, user=42):
    return {"callback_query": {"id": "q", "data": data, "from": {"id": user},
                               "message": {"chat": {"id": user}}}}


def labels_sent(telegram):
    payload = telegram.calls[-1][1]
    return payload["text"], [b for row in payload["reply_markup"]["inline_keyboard"] for b in row]


def test_chinesememe_is_simplified_and_chinesememe_tw_is_traditional():
    bot, telegram, _ = make_bot(StubLLM())
    bot.handle({"message": {"chat": {"id": 42}, "text": "/chinesememe"}})
    text, buttons = labels_sent(telegram)
    assert text == "选一个主题：" and buttons[0] == {"text": "随机一张", "callback_data": "zs:random"}
    assert [b["text"] for b in buttons[1:]] == [t["label"] for t in THEMES_HANS]
    assert all(b["callback_data"].startswith("zs:") for b in buttons)

    bot.handle({"message": {"chat": {"id": 42}, "text": "/chinesememe_tw"}})
    text, buttons = labels_sent(telegram)
    assert text == "選一個主題：" and buttons[0] == {"text": "隨機一張", "callback_data": "zh:random"}
    assert [b["text"] for b in buttons[1:]] == [t["label"] for t in THEMES_ZH]


def test_chinese_is_always_written_in_traditional_and_shown_in_the_script_asked_for():
    llm = StubLLM(GOOD_ZH, GOOD_ZH)
    bot, telegram, _ = make_bot(llm)
    bot.handle(tap("zh:nianfo"))
    bot.handle(tap("zs:nianfo"))
    trad = next(t for t in THEMES_ZH if t["id"] == "nianfo")
    assert llm.calls == [f"主題: {as_topic(trad)}"] * 2  # one source for both scripts
    assert [s[0] for s in telegram.sent] == ["photo", "photo"]
    assert telegram.sent[0][2] != telegram.sent[1][2]  # drawn in two different scripts
    # A fresh meme gets thumbs only (no Report): it is not in the pool yet.
    assert [[b["text"] for b in m["inline_keyboard"][0]] for m in telegram.markups] == [
        ["👍", "👎"], ["👍", "👎"]]
    held = bot.feedback.store.items("fresh")
    assert len(held) == 2 and all(h["lang"] == "zh" and h["slots"] == GOOD_ZH["slots"]
                                  for h in held)  # stored in Traditional either way


def test_random_serves_the_vetted_chinese_pool_without_the_llm():
    llm = StubLLM()
    bot, telegram, _ = make_bot(llm, pool_memes=[POOL_ZH, POOL_EN])
    bot.handle(tap("zs:random"))
    bot.handle(tap("zh:random"))
    assert llm.calls == [] and [s[0] for s in telegram.sent] == ["photo", "photo"]
    simplified_buttons, traditional_buttons = (m["inline_keyboard"][0] for m in telegram.markups)
    assert [b["callback_data"] for b in simplified_buttons] == ["up:z1", "dn:z1", "rp:z1"]
    assert simplified_buttons[2]["text"] == "举报" and traditional_buttons[2]["text"] == "檢舉"
    assert telegram.sent[0][2] != telegram.sent[1][2]  # the two scripts are drawn differently


def test_chineserandom_is_a_command_of_its_own():
    llm = StubLLM()
    bot, telegram, _ = make_bot(llm, pool_memes=[POOL_ZH, POOL_EN])
    for command in ("/chineserandom", "/chineserandom_tw"):
        bot.handle({"message": {"chat": {"id": 42}, "text": command}})
    assert llm.calls == [] and telegram.calls == []  # a meme straight away, no list, no LLM
    assert [s[0] for s in telegram.sent] == ["photo", "photo"]
    assert [m["inline_keyboard"][0][2]["text"] for m in telegram.markups] == ["举报", "檢舉"]
    assert telegram.markups[0]["inline_keyboard"][0][0]["callback_data"] == "up:z1"

    empty_bot, empty_telegram, _ = make_bot(llm, pool_memes=[POOL_EN])
    empty_bot.handle({"message": {"chat": {"id": 42}, "text": "/chineserandom"}})
    assert empty_telegram.sent == [("message", 42, CHINESE[HANS]["empty"])]


def test_random_writes_a_fresh_one_while_the_chinese_pool_is_empty():
    llm = StubLLM(GOOD_ZH)
    bot, telegram, _ = make_bot(llm, pool_memes=[POOL_EN])
    bot.handle(tap("zs:random"))
    assert len(llm.calls) == 1 and llm.calls[0].startswith("主題: ")


def test_the_pools_are_separate():
    bot, telegram, pool = make_bot(StubLLM(), pool_memes=[POOL_ZH, POOL_EN])
    assert [m["id"] for m in pool.approved()] == ["a1"]  # the website and /random: English
    assert [m["id"] for m in pool.approved("zh")] == ["z1"]
    bot.handle({"message": {"chat": {"id": 42}, "text": "/random"}})
    assert telegram.markups[0]["inline_keyboard"][0][0]["callback_data"] == "up:a1"


def test_chinese_fallbacks_are_in_the_right_script():
    for prefix, messages in (("zh:", MESSAGES_ZH), ("zs:", MESSAGES_HANS)):
        bot, telegram, _ = make_bot(StubLLM(GOOD_ZH, {"declined": True}), per_ip=2)
        for _ in range(3):
            bot.handle(tap(f"{prefix}nianfo"))
        assert telegram.sent[1] == ("message", 42, messages["declined"])
        assert telegram.sent[2] == ("message", 42, messages["limit"])
    # With a Chinese pool, the fallback comes with a meme from it.
    bot, telegram, _ = make_bot(StubLLM({"declined": True}), pool_memes=[POOL_ZH])
    bot.handle(tap("zs:nianfo"))
    assert telegram.sent[0][0] == "photo" and telegram.sent[0][3] == MESSAGES_HANS["declined"]
    assert CHINESE[HANS]["messages"] is MESSAGES_HANS


# --- the Chinese pool's generator and vetting ---

def test_the_generator_keeps_each_language_to_itself():
    pool = Pool(MemoryStore())
    pool.add(POOL_EN)
    pool.add(POOL_ZH)
    now = lambda: datetime(2026, 10, 3, 1, 0, tzinfo=timezone.utc)  # noqa: E731
    new_zh = {"template_id": "drake", "slots": {"rejected": "早起做早課", "preferred": "再睡五分鐘"}}
    llm = StubLLM([new_zh], [{"n": 1, "pass": True}])
    added = generator.run(pool, llm, TEMPLATES, len(TEMPLATES), "pending", now, "zh")
    assert [m["id"] for m in added] == ["gen-zh-20261003-010000-01"] and added[0]["lang"] == "zh"
    writer, reviewer = llm.calls
    assert "專心念佛" in writer and "Sitting" not in writer  # shown the Chinese pool only
    assert "庫裡已有" in writer and "one-does-not-simply" not in writer
    assert [m["lang"] for m in pool.all()] == ["en", "zh", "zh"]
    assert len(pool.approved("zh")) == 1  # the new one waits for the owner


def test_the_owner_vets_chinese_memes_in_simplified():
    bot, telegram, pool = make_bot(StubLLM(), owner=99)
    pending = dict(POOL_ZH, id="z2", status="pending")
    pool.add(pending)
    bot.ask_owner(pending)
    simplified_picture = bot.draw(pending, HANS)
    assert telegram.sent[0][2] == simplified_picture != bot.draw(pending, "zh")
    bot.handle(tap("ok:z2", user=99))
    assert [m["id"] for m in pool.approved("zh")] == ["z2"]
