import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from multilingual import caption_font, speech_units, wrap_unspaced

SAMPLES = {
    "বৃষ্টির বিকেলে মীরা": "Nirmala UI", "बारिश की शाम": "Nirmala UI", "மழை மாலை": "Nirmala UI",
    "بارش کی شام": "Segoe UI", "مساء ممطر": "Segoe UI", "雨天的下午": "Microsoft YaHei",
    "雨の午後です": "Yu Gothic UI", "비 오는 오후": "Malgun Gothic", "บ่ายวันฝนตก": "Leelawadee UI",
    "Una tarde de lluvia": "Segoe UI", "Дождливый день": "Segoe UI",
}


@pytest.mark.parametrize("text,font", SAMPLES.items())
def test_caption_font_follows_the_script(text, font):
    assert caption_font(text) == font


def test_unspaced_lines_wrap_and_spaced_lines_do_not():
    chinese = "这是一个关于茶园和一杯热茶的很长很长的故事字幕"
    wrapped = wrap_unspaced(chinese, limit=12)
    assert "\n" in wrapped and wrapped.replace("\n", "") == chinese
    assert all(len(line) <= 12 for line in wrapped.splitlines())
    spanish = "Una historia muy larga sobre una taza de té caliente en el jardín"
    assert wrap_unspaced(spanish, limit=12) == spanish


def test_speech_units_make_chinese_and_hindi_comparable_to_english():
    english = speech_units("A story in every cup")                  # 16 letters
    assert speech_units("每一杯茶的故事") == 21                       # 7 syllables
    assert speech_units("कहानी") > speech_units("कहन")              # spacing vowel signs count
    assert english == 16


def test_overlong_chinese_narration_is_refused_before_paying(tmp_path):
    from unittest.mock import patch
    from speech import narration
    with patch("speech.urlopen") as call:
        with pytest.raises(ValueError, match="nothing was charged"):
            narration({"dialogue": "这是一个非常长的旁白" * 4}, ("openai", "m", "v", "k"), tmp_path, 4)
    call.assert_not_called()


def test_caption_files_have_neutral_names_and_wrapped_cjk(tmp_path):
    sys.path.insert(0, str(ROOT / "tools" / "windows-bangla"))
    import bangla_tools
    (tmp_path / "audio").mkdir()
    long = "这是一个关于茶园和一杯热茶的很长很长的故事字幕"
    (tmp_path / "audio" / "timing.json").write_text(json.dumps({"segments": [
        {"start": 0.5, "end": 3.0, "vo": long, "caption": long}]}), encoding="utf-8")
    out = bangla_tools.srt(tmp_path)
    assert out.name == "captions.srt"
    assert "\n" in out.read_text(encoding="utf-8").split("\n", 2)[2].strip()


def test_language_catalog_has_real_voice_ids_for_every_language():
    catalog = json.loads((ROOT / "web" / "languages.json").read_text(encoding="utf-8"))
    codes = {lang["code"] for lang in catalog}
    assert {"bn-BD", "hi-IN", "ur-PK", "zh-CN", "es-ES", "ar-SA", "en-US"} <= codes
    assert len(codes) == len(catalog)
    for lang in catalog:
        assert lang["voices"], lang["code"]
        for voice, name, gender in lang["voices"]:
            assert voice.startswith(lang["code"] + "-") and voice.endswith("Neural") and gender in "FM"


engine = None


@pytest.fixture
def res():
    global engine
    sys.path.insert(0, str(ROOT / "skills/cinematic-film/scripts"))
    engine = pytest.importorskip("engine")
    import skia

    class Res:
        def font(self, name, size):
            tf, _ = engine.resolve_typeface(name)
            f = skia.Font(tf, size); f.setSubpixel(True)
            return f
    return Res()


def test_engine_keeps_latin_on_the_tracked_path(res):
    assert engine._shaped_font(res, "serif", 40, "A Story in Every Cup — señor") is None
    f = res.font("serif", 40)
    plain = sum(f.getWidths(f.textToGlyphs("Cup"))) + 0.1 * 40 * 2
    assert engine.text_width(res, "Cup", 40, track=0.1) == pytest.approx(plain)


@pytest.mark.parametrize("text,rtl", [("चाय की कहानी", False), ("چائے کی کہانی", True), ("每一杯茶的故事", False),
                                      ("চা বাগানের গল্প", False), ("قصة الشاي", True)])
def test_engine_shapes_other_scripts_with_a_matching_font(res, text, rtl):
    import skia
    shaped = engine._shaped_font(res, "serif", 40, text)
    assert shaped is not None and shaped[1] is rtl
    f, _ = shaped
    assert 0 not in f.textToGlyphs(text.replace(" ", ""))          # the chosen font has every glyph
    width = engine.text_width(res, text, 40)
    assert 40 < width <= 40 * len(text)                              # CJK glyphs are exactly one em wide
    surface = skia.Surface(800, 120)
    canvas = surface.getCanvas(); canvas.clear(skia.ColorWHITE)
    assert engine.draw_text(canvas, res, text, 20, 80, 40, rgb=(0, 0, 0)) == pytest.approx(width)
    pixels = surface.makeImageSnapshot().toarray()
    assert (pixels[:, :, 0] < 128).sum() > 200                       # ink was drawn
