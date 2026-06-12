"""mt_vllm 語言護欄（lang_guard_ok）單元測試。

背景：破碎的 STT partial 會讓翻譯模型偶爾原文照抄，
導致 en 串流出現簡體中文（2026-06-11 手測發現）。
"""

from stages.mt_vllm.stage import lang_guard_ok


def test_english_target_rejects_chinese_echo():
    # 真實案例：zh→en 卻照抄簡體原文
    assert not lang_guard_ok("我们将这些课程中的", "en")


def test_english_target_accepts_english():
    assert lang_guard_ok("We will demonstrate a real-time translation system.", "en")


def test_english_target_tolerates_sparse_cjk():
    # 譯文夾帶少量原文專名（如人名）不應誤殺
    assert lang_guard_ok('The speaker, known as "小明", greeted the audience warmly.', "en")


def test_cjk_target_rejects_english_echo():
    assert not lang_guard_ok("Hello everyone, welcome to the conference.", "zh")


def test_cjk_target_accepts_chinese():
    assert lang_guard_ok("各位來賓大家好，歡迎參加發表會。", "zh")


def test_japanese_target_accepts_kana():
    assert lang_guard_ok("皆さん、こんにちは。発表会へようこそ。", "ja")


def test_empty_output_rejected():
    assert not lang_guard_ok("", "en")
    assert not lang_guard_ok("", "zh")
