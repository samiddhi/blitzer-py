"""Check the two fixed-purpose skip lists with everyday English examples."""

import json

import pytest

from blitzer.config import get_config
from blitzer.core import BlitzerService
from test_cli import make_runner
from blitzer.cli import cli


@pytest.fixture
def english(tmp_path):
    """Build a small dictionary with irregular verbs and plural nouns."""
    source = tmp_path / "english-source"
    source.mkdir()
    (source / "config.toml").write_text(
        'format_version = 2\n[metadata]\nlanguage_code = "eng"\n'
        'language_name = "English"\nversion = "0.1.0"\nauthor = "Test"\n'
        '[tokenization]\nprofile = "default"\n'
        '[normalization]\nlowercase = true\nsubstitutions = []\n'
    )
    families = {
        "be": "be am is are was were being been",
        "walk": "walk walks walked walking",
        "cat": "cat cats", "dog": "dog dogs",
    }
    rows = [f"{word}\t{basic}\n" for basic, words in families.items() for word in words.split()]
    (source / "forms.tsv").write_text("form\tlemma\n" + "".join(rows))
    service = BlitzerService(use_config=False, plugins_dir=tmp_path / "packs")
    service.build_plugin(source)
    return service


@pytest.mark.parametrize("basic", [False, True])
def test_exact_words_do_not_skip_other_be_forms(english, tmp_path, basic):
    """Knowing be and am must leave is and are counted in either display."""
    exact = tmp_path / "exact.txt"
    exact.write_text("# I know these spellings\nBE\nam\ncat\nsally-anne\n")
    entries = english.blitz(
        "Be am. Is are are! Cat cats.", "eng", lemmatize=basic,
        skip_exact_words_file=exact, context=True,
    )
    expected = {"be": 3, "cat": 1} if basic else {"are": 2, "is": 1, "cats": 1}
    assert {entry.term: entry.count for entry in entries} == expected
    assert all(context.text != "Be am." for entry in entries for context in entry.contexts)


@pytest.mark.parametrize("basic", [False, True])
def test_word_families_skip_all_be_forms_and_plurals(english, tmp_path, basic):
    """One basic word represents its dictionary family, including irregular forms."""
    families = tmp_path / "families.txt"
    families.write_text("be\ncat\n")
    entries = english.blitz(
        "be am is are was were being been cat cats dogs", "eng",
        lemmatize=basic, skip_word_families_file=families,
    )
    assert [(entry.term, entry.count) for entry in entries] == [("dog" if basic else "dogs", 1)]


def test_config_paths_and_independent_cli_replacement(english, tmp_path):
    """Replacing the exact list keeps the configured family list active."""
    (tmp_path / "exact.txt").write_text("walked\n")
    (tmp_path / "families.txt").write_text("be\n")
    replacement = tmp_path / "replacement.txt"
    replacement.write_text("walking\n")
    config = tmp_path / "config.toml"
    config.write_text(
        '[languages.eng]\nskip_exact_words_file = "exact.txt"\n'
        'skip_word_families_file = "families.txt"\n'
    )
    assert get_config(config)["languages"]["eng"]["skip_exact_words_file"] == tmp_path / "exact.txt"
    result = make_runner().invoke(cli, [
        "blitz", "-C", str(config), "-P", str(english.plugins_dir), "-l", "eng",
        "-t", "am walked walking", "--skip-exact-words-file", str(replacement), "-o", "json",
    ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == [{"term": "walked", "count": 1}]


@pytest.mark.parametrize("basic", [False, True])
@pytest.mark.parametrize("kind,expected", [
    ("exact-words", {"are", "walked"}), ("word-families", {"be", "walk"}),
])
def test_updates_choose_one_list_and_do_not_follow_display(english, tmp_path, kind, expected, basic):
    """Preview writes nothing; an explicit target receives only its kind of words."""
    exact, families = tmp_path / "exact.txt", tmp_path / "families.txt"
    args = [
        "blitz", "-n", "-P", str(english.plugins_dir), "-l", "eng",
        "-t", "are walked", "--skip-exact-words-file", str(exact),
        "--skip-word-families-file", str(families), "--update-list", kind,
    ]
    if basic:
        args.append("-L")
    preview = make_runner().invoke(cli, [*args, "-T", "-H"])
    assert preview.exit_code == 0, preview.output
    assert not exact.exists() and not families.exists()
    assert not english.config["locations"]["history_file"].exists()
    update = make_runner().invoke(cli, [*args, "-u"])
    assert update.exit_code == 0, update.output
    target, other = (exact, families) if kind == "exact-words" else (families, exact)
    assert set(target.read_text().splitlines()) == expected
    assert not other.exists()


def test_update_requires_an_explicit_list(english, tmp_path):
    """Choosing a skip file does not silently choose an update destination."""
    result = make_runner().invoke(cli, [
        "blitz", "-n", "-P", str(english.plugins_dir), "-l", "eng", "-t", "are",
        "--skip-exact-words-file", str(tmp_path / "exact.txt"), "-T",
    ])
    assert result.exit_code == 1
    assert "Choose --update-list" in result.stderr


def test_show_all_and_conflicting_flags(english, tmp_path):
    """Show-all bypasses configured lists but rejects contradictory explicit files."""
    exact = tmp_path / "exact.txt"
    exact.write_text("am\n")
    config = tmp_path / "config.toml"
    config.write_text('[languages.eng]\nskip_exact_words_file = "exact.txt"\n')
    configured = BlitzerService(config, plugins_dir=english.plugins_dir)
    assert configured.blitz("am", "eng") == []
    assert configured.blitz("am", "eng", no_exclusions=True)[0].term == "am"
    with pytest.raises(ValueError, match="cannot be combined"):
        english.blitz("am", "eng", no_exclusions=True, skip_exact_words_file=exact)
    with pytest.raises(ValueError, match="legacy"):
        english.blitz("am", "eng", skip_exact_words_file=exact, filter_by="lemmas")


@pytest.mark.parametrize("legacy", ["known_file = 'old.txt'", "exclusions = []",
                                    "forms_only = []", "filter_by = 'forms'"])
def test_mixed_config_explains_migration(tmp_path, legacy):
    """A mixed config must fail instead of silently changing its list meanings."""
    config = tmp_path / "mixed.toml"
    config.write_text("[languages.eng]\nskip_exact_words_file = 'exact.txt'\n" + legacy)
    with pytest.raises(ValueError, match="instead of mixing"):
        get_config(config)


def test_ambiguous_family_keeps_other_candidates(service, tmp_path):
    """Skipping the biti family does not remove unrelated je candidates."""
    families = tmp_path / "families.txt"
    families.write_text("biti\n")
    assert {entry.term for entry in service.blitz(
        "je", "slv", lemmatize=True, skip_word_families_file=families
    )} == {"jesti", "on"}


def test_slovenian_sem_and_biti_leave_sva_counted(source, tmp_path):
    """Knowing two exact spellings must not discard another form of biti."""
    forms = source / "forms.tsv"
    forms.write_text(forms.read_text() + "sva\tbiti\n")
    service = BlitzerService(use_config=False, plugins_dir=tmp_path / "slv-packs")
    service.build_plugin(source)
    exact = tmp_path / "slv-exact.txt"
    exact.write_text("sem\nbiti\n")
    entries = service.blitz(
        "sem biti sva sva", "slv", lemmatize=True,
        exclude_unknown=True, skip_exact_words_file=exact,
    )
    assert [(entry.term, entry.count) for entry in entries] == [("biti", 2)]


def test_base_accepts_exact_words_but_requires_dictionary_for_families(tmp_path):
    """Dictionary-free mode can skip spellings but cannot recognize families."""
    path = tmp_path / "exact.txt"
    path.write_text("cat\n")
    service = BlitzerService(use_config=False)
    assert service.blitz("cat cats", "base", skip_exact_words_file=path)[0].term == "cats"
    with pytest.raises(ValueError, match="base has no dictionary"):
        service.blitz("cat cats", "base", skip_word_families_file=path)


def test_bundled_english_exact_words_skip_before_display(tmp_path):
    """Exact skipping works with bundled data regardless of missing family links."""
    path = tmp_path / "exact.txt"
    path.write_text("be\nam\n")
    service = BlitzerService(use_config=False)
    text = "be am is are was were being been"
    assert {entry.term for entry in service.blitz(
        text, "eng", skip_exact_words_file=path
    )} == {"is", "are", "was", "were", "being", "been"}
    path.write_text("\n".join(text.split()) + "\n")
    assert service.blitz(text, "eng", lemmatize=True, skip_exact_words_file=path) == []
