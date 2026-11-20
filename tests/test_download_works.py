"""Search groups keep one output folder and one OpenAlex filter each."""

import pytest

import download_works


def _group(name: str, keywords: list[str], subfields: str = "1102", limit: object = None) -> dict:
    return {
        "name": name,
        "keywords": keywords,
        "subfields": subfields,
        "limit": limit,
    }


def test_distinct_groups_keep_separate_folders():
    prepared = download_works.prepare_searches(
        [
            _group("hydropower", ["hydropower"]),
            _group("crops", ["rice yield", "wheat yield"], subfields="1102|1110"),
        ]
    )

    assert [item["name"] for item in prepared] == ["hydropower", "crops"]
    assert prepared[1]["keywords"] == ["rice yield", "wheat yield"]
    assert prepared[1]["subfields"] == "1102|1110"
    assert prepared[1]["limit"] is None


def test_groups_that_share_a_folder_exit(capsys):
    with pytest.raises(SystemExit) as exc:
        download_works.prepare_searches(
            [
                _group("rice", ["rice yield"]),
                _group("rice!", ["wheat yield"]),
            ]
        )

    assert exc.value.code == 1
    error = capsys.readouterr().err
    assert "rice" in error
    assert "rice!" in error


def test_group_names_that_differ_only_by_case_exit(capsys):
    with pytest.raises(SystemExit) as exc:
        download_works.prepare_searches(
            [
                _group("Crops", ["rice yield"]),
                _group("crops", ["wheat yield"]),
            ]
        )

    assert exc.value.code == 1
    error = capsys.readouterr().err
    assert "Crops" in error
    assert "crops" in error


def test_boolean_limit_exits():
    with pytest.raises(SystemExit) as exc:
        download_works.parse_limit(True, "crops")

    assert exc.value.code == 1


def test_filter_joins_keyword_phrases_and_subfields():
    year = download_works.YEAR_FROM - 1
    filt = download_works.filter_for(["rice yield", "wheat yield"], "1102|1110")

    assert filt == (
        f"publication_year:>{year},type:article,"
        "title_and_abstract.search:rice yield|wheat yield,"
        "primary_topic.subfield.id:1102|1110"
    )


def test_filter_omits_subfields_when_empty():
    filt = download_works.filter_for(["hydropower"], "")

    assert "primary_topic.subfield.id" not in filt
    assert filt.endswith("title_and_abstract.search:hydropower")
