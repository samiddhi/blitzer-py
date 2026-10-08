"""Check language boundaries end to end, including pack round trips."""

import sys
from unittest.mock import patch

import pytest
from blitzer.config import load_plugin_config
from blitzer.core import BlitzerService
from blitzer.languages import CATALOG
from blitzer.tokenization import _japanese_tokenizer, tokenize, word


@pytest.mark.parametrize("profile,text,expected", [
    ("default", "don't well-known abc123def", ["don't", "well", "known", "abc", "def"]),
    ("joiners", "می‌روم رفت", ["می‌روم", "رفت"]),
    ("joiners", "क्‍ष और", ["क्‍ष", "और"]),
    ("joiners", "foo\u200c bar", ["foo", "bar"]),
    ("middle-dot", "col·legi. l·l", ["col·legi", "l·l"]),
    ("colon-glottal", "'o'odham ba:b", ["'o'odham", "ba:b"]),
    ("final-glottal", "gatgëhjista' next", ["gatgëhjista'", "next"]),
    ("internal-dot", "gatáa.ang. other", ["gatáa.ang", "other"]),
    ("hebrew", 'צה״ל צה"ל ג׳', ['צה״ל', 'צה"ל', 'ג׳']),
    ("mongolian", "ᠠ\u180eᠨ ᠠ", ["ᠠ\u180eᠨ", "ᠠ"]),
    ("tone", "m⁵mà¹ chi¹⁴chi⁴ 123", ["m⁵mà¹", "chi¹⁴chi⁴"]),
    ("tone-ascii", "toho1ʔo 123", ["toho1ʔo"]),
    ("tone-hyphen", "u-sa¹na² ni¹-chi³chin⁴", ["u-sa¹na²", "ni¹-chi³chin⁴"]),
    ("pali", "eva”haṃ", ["eva”haṃ"]),
])
def test_profiles_preserve_source_offsets(profile, text, expected):
    """Changing boundaries must never change the highlighted substring."""
    tokens = list(tokenize(text, profile))
    assert [t.text for t in tokens] == expected
    assert all(text[t.start:t.end] == t.text for t in tokens)
    assert all(word(t.text, profile) for t in tokens)


def make_pack(tmp_path, code, profile, forms, frequencies=""):
    """Build a tiny explicit-profile pack for integration checks."""
    source = tmp_path / f"source-{code}"
    source.mkdir()
    (source / "config.toml").write_text(
        'format_version = 2\n[metadata]\n'
        f'language_code = "{code}"\nlanguage_name = "{code.upper()}"\n'
        'version = "0.2.0"\nauthor = "Test"\n'
        f'[tokenization]\nprofile = "{profile}"\n'
        '[normalization]\nlowercase = true\nsubstitutions = []\n'
    )
    (source / "forms.tsv").write_text('form\tlemma\n' + forms)
    if frequencies:
        (source / "frequencies.tsv").write_text('term\tfrequency\n' + frequencies)
    service = BlitzerService(use_config=False, plugins_dir=tmp_path / "packs")
    service.build_plugin(source)
    return service


def test_tone_pack_known_frequency_context_install_round_trip(tmp_path):
    """Check all consumers accept the same tone-bearing lexical entries."""
    service = make_pack(tmp_path, "azg", "tone", "toan⁵³\tm⁵mà¹\n", "m⁵mà¹\t7\n")
    entries = service.blitz("Toan⁵³! Toan⁵³.", "azg", lemmatize=True,
                            context=True, sort="global-frequency", track_known=True)
    assert [(e.term, e.count, e.global_frequency) for e in entries] == [("m⁵mà¹", 2, 7)]
    assert entries[0].contexts[0].text == "Toan⁵³!"
    known = tmp_path / "known.txt"
    service.update_known("azg", entries, path=known, dry_run=False)
    assert service.blitz("toan⁵³", "azg", known_file=known, filter_by="lemmas") == []
    archive = service.package_plugin("azg", tmp_path / "archives")
    assert archive.exists()
    installed = BlitzerService(use_config=False, plugins_dir=tmp_path / "installed")
    installed.install_plugin(service.plugins_dir / "azg")
    assert all(c.status == "pass" for c in installed.check_plugin("azg"))
    assert installed.blitz("toan⁵³", "azg", lemmatize=True)[0].term == "m⁵mà¹"


def test_elision_fallback_keeps_dictionary_words_and_offsets(tmp_path):
    """Only split unknown elisions when the suffix has a usable entry."""
    service = make_pack(tmp_path, "fra", "elision-french",
                        "homme\thomme\naujourd’hui\taujourd’hui\n")
    entries = service.blitz("L’homme. Aujourd’hui.", "fra", lemmatize=True,
                            exclude_unknown=True, context=True)
    assert {e.term for e in entries} == {"homme", "aujourd’hui"}
    context = next(e for e in entries if e.term == "homme").contexts[0]
    assert context.text[context.highlight_start:context.highlight_end] == "homme"
    known = tmp_path / "known.txt"
    known.write_text("homme\n")
    assert service.blitz("l’homme", "fra", known_file=known, exclude_unknown=True) == []


@pytest.mark.parametrize("code,name", [
    ("ces", "Czech"), ("slk", "Slovak"), ("san", "Sanskrit"),
    ("syc", "Classical Syriac"), ("slv", "Slovenian"),
])
def test_catalog_repairs_generated_names(code, name):
    """The reviewed catalog must not contain headings or code placeholders."""
    assert CATALOG[code]["name"] == name


def test_unknown_and_legacy_profiles_rejected(tmp_path):
    """Downloaded packs cannot select Python code or unknown profiles."""
    service = make_pack(tmp_path, "cat", "middle-dot", "col·legi\tcol·legi\n")
    path = service.plugins_dir / "cat" / "config.toml"
    path.write_text(path.read_text().replace("middle-dot", "module:function"))
    with pytest.raises(ValueError, match="Unknown tokenization"):
        load_plugin_config(path.parent)
    path.write_text(path.read_text().replace("module:function", "default")
                    .replace("format_version = 2", "format_version = 1"))
    with pytest.raises(ValueError, match="require format_version = 2"):
        load_plugin_config(path.parent)


def test_unavailable_segmenter_is_explicit():
    """No fallback may silently interpret unspaced prose as whole runs."""
    with pytest.raises(ValueError, match="requires a lexical segmenter"):
        list(tokenize("रामोऽस्ति", "unavailable"))


def test_japanese_missing_dependency_message():
    """A machine without optional packages receives an actionable error."""
    _japanese_tokenizer.cache_clear()
    with patch.dict(sys.modules, {"sudachipy": None}):
        with pytest.raises(ValueError, match=r"bltzr\[japanese\]"):
            list(tokenize("食べた", "sudachi"))
    _japanese_tokenizer.cache_clear()


def test_japanese_adapter_dictionary_fallback(tmp_path):
    """An inflected source span can look up the analyzer's dictionary form."""
    pytest.importorskip("sudachipy")
    pytest.importorskip("sudachidict_core")
    service = make_pack(tmp_path, "jpn", "sudachi", "食べる\t食べる\n")
    text = "🍚を食べた。食べる。"
    tokens = list(tokenize(text, "sudachi"))
    assert all(text[t.start:t.end] == t.text for t in tokens)
    assert any(t.text == "食べ" and t.lookup == "食べる" for t in tokens)
    entries = service.blitz(text, "jpn", lemmatize=True, exclude_unknown=True, context=True)
    assert [(e.term, e.count) for e in entries] == [("食べる", 2)]
    assert entries[0].contexts[0].text == "🍚を食べた。"
    known = tmp_path / "known.txt"
    known.write_text("食べる\n")
    assert service.blitz("食べた", "jpn", known_file=known,
                         filter_by="lemmas", exclude_unknown=True) == []
    assert service.blitz("食べた", "jpn", known_file=known,
                         filter_by="forms", lemmatize=True, exclude_unknown=True)[0].term == "食べる"
