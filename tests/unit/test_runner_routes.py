"""runner route_by 展開（§6.3）單元測試。"""

import pytest

from services.runner.__main__ import expand_routes


def _node(routes, config=None):
    return {"id": "tts", "route_by": "lang", "routes": routes, "config": config or {}}


def test_single_route_injects_langs():
    out = expand_routes(_node({"[zh, ja]": "tts_cosyvoice2@0.1"}, {"fp16": True}))
    assert len(out) == 1
    assert out[0]["use"] == "tts_cosyvoice2@0.1"
    assert out[0]["config"]["langs"] == ["zh", "ja"]
    assert out[0]["config"]["fp16"] is True  # 共用 config 繼承


def test_wildcard_gets_exclusion_of_explicit_langs():
    out = expand_routes(_node({
        "[zh, ja, ko]": "tts_cosyvoice2@0.1",
        "[en, fr]": "tts_kokoro@0.9",
        "*": "tts_mms@0.1",
    }))
    assert [n["use"] for n in out] == ["tts_cosyvoice2@0.1", "tts_kokoro@0.9", "tts_mms@0.1"]
    wild = out[-1]["config"]
    assert wild["langs"] == "*"
    assert set(wild["langs_exclude"]) == {"zh", "ja", "ko", "en", "fr"}


def test_expanded_ids_stay_distinct():
    out = expand_routes(_node({"[zh]": "a@1", "[en]": "b@1", "*": "c@1"}))
    ids = [n["id"] for n in out]
    assert len(ids) == len(set(ids))


def test_only_lang_routing_supported():
    with pytest.raises(SystemExit):
        expand_routes({"id": "x", "route_by": "speaker", "routes": {}})


def test_bad_route_key_rejected():
    with pytest.raises(SystemExit):
        expand_routes(_node({"zh": "a@1"}))  # 缺 [] 清單字面值


def test_set_override_parses_yaml_types():
    from services.runner.__main__ import apply_overrides

    nodes = [{"id": "stt"}, {"id": "mt", "config": {"target_langs": ["zh"]}}]
    apply_overrides(nodes, ["stt.pace=0.5", "stt.source=a.wav",
                            "mt.target_langs=[zh, en]", "stt.fp16=false"])
    assert nodes[0]["config"] == {"pace": 0.5, "source": "a.wav", "fp16": False}
    assert nodes[1]["config"]["target_langs"] == ["zh", "en"]
