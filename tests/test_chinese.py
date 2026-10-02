"""/chinesememe: the Chinese voice, its themes, and drawing Chinese text."""
import io
from pathlib import Path

from PIL import Image

from dharmeme.catalog import load_catalog
from dharmeme.limits import Limits
from dharmeme.pool import Pool
from dharmeme.prompt import MemeError, system_prompt, validate, write_meme
from dharmeme.render import Renderer, fit_text, has_cjk, tokens, wrap
from dharmeme.store import MemoryStore
from dharmeme.telegram import MESSAGES_ZH, PICK_ZH, Bot
from dharmeme.themes import THEMES_DIR, as_topic, load_themes
from test_bot import FakeTelegram
from test_engine import StubLLM

import pytest

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "templates" / "fonts"
TEMPLATES = load_catalog()
THEMES_ZH = load_themes(THEMES_DIR / "zh.yaml")
RENDERER = Renderer(ROOT / "templates" / "images", FONTS / "Anton-Regular.ttf",
                    FONTS / "NotoSansTC.ttf")
GOOD_ZH = {"template_id": "drake", "slots": {"rejected": "放下手機", "preferred": "放下功課"}}

# Every character one font-size wide: close enough to a square Chinese glyph.
measure = lambda text, size: len(text) * size  # noqa: E731


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


def test_chinese_text_is_drawn_with_the_chinese_font():
    assert has_cjk("放下") and not has_cjk("Letting go")
    template = next(t for t in TEMPLATES if t["id"] == "drake")
    drawn = Image.open(io.BytesIO(RENDERER.render(template, GOOD_ZH["slots"])))
    blank = Image.open(io.BytesIO(RENDERER.render(template, {"rejected": " ", "preferred": " "})))
    assert drawn.size == blank.size and drawn.tobytes() != blank.tobytes()
    # Anton has no Chinese glyphs: the two fonts must measure Chinese differently.
    assert RENDERER.font(40, True).getlength("放下") != RENDERER.font(40).getlength("放下")


def test_chinese_themes_are_their_own_list():
    assert len(THEMES_ZH) >= 15
    assert all(has_cjk(t["label"]) and has_cjk(t["brief"]) for t in THEMES_ZH)
    assert all(len(f"zh:{t['id']}") <= 64 for t in THEMES_ZH)
    assert {"nianfo", "chisu", "suiyuan"} <= {t["id"] for t in THEMES_ZH}


def test_the_chinese_voice_has_its_own_prompt_and_half_the_characters():
    prompt = system_prompt(TEMPLATES, "zh")
    assert "繁體中文" in prompt and "漢傳佛教" in prompt
    assert "rejected (最多 35 個字)" in prompt  # 70 Latin characters -> 35 Chinese ones
    assert validate(GOOD_ZH, TEMPLATES, "zh") == GOOD_ZH
    too_long = {"template_id": "drake", "slots": {"rejected": "字" * 36, "preferred": "好"}}
    with pytest.raises(MemeError):
        validate(too_long, TEMPLATES, "zh")
    assert validate(too_long, TEMPLATES)  # the same length is fine in English


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


def make_bot(llm, per_ip=5):
    store = MemoryStore()
    telegram = FakeTelegram()
    bot = Bot(Pool(store), Limits(store, per_ip=per_ip), lambda: llm, TEMPLATES, RENDERER,
              telegram, None, None, [], THEMES_ZH)
    return bot, telegram


def tap(theme_id, user=42):
    return {"callback_query": {"id": "q", "data": f"zh:{theme_id}", "from": {"id": user},
                               "message": {"chat": {"id": user}}}}


def test_chinesememe_lists_the_chinese_themes():
    bot, telegram = make_bot(StubLLM())
    bot.handle({"message": {"chat": {"id": 42}, "text": "/chinesememe"}})
    method, payload = telegram.calls[0]
    assert payload["text"] == PICK_ZH
    buttons = [b for row in payload["reply_markup"]["inline_keyboard"] for b in row]
    assert buttons[0] == {"text": "隨機一張", "callback_data": "zh:random"}
    assert [b["text"] for b in buttons[1:]] == [t["label"] for t in THEMES_ZH]


def test_tapping_a_chinese_theme_writes_in_the_chinese_voice():
    llm = StubLLM(GOOD_ZH, GOOD_ZH)
    bot, telegram = make_bot(llm)
    bot.handle(tap("nianfo"))
    theme = next(t for t in THEMES_ZH if t["id"] == "nianfo")
    assert llm.calls == [f"主題: {as_topic(theme)}"]
    assert telegram.sent[0][0] == "photo"
    bot.handle(tap("random"))
    assert len(llm.calls) == 2 and llm.calls[1].startswith("主題: ")


def test_chinese_fallbacks_are_chinese_messages():
    bot, telegram = make_bot(StubLLM(GOOD_ZH, {"declined": True}), per_ip=2)
    for _ in range(3):
        bot.handle(tap("nianfo"))
    assert telegram.sent[1] == ("message", 42, MESSAGES_ZH["declined"])
    assert telegram.sent[2] == ("message", 42, MESSAGES_ZH["limit"])
