"""Keyword download script keeps one output folder per keyword."""

import pytest

import download_works


def test_distinct_keywords_get_separate_folders():
    assigned = download_works.assign_output_folders(["rice", "wheat"])

    assert assigned == [("rice", "rice"), ("wheat", "wheat")]


def test_keywords_that_share_a_folder_exit(capsys):
    with pytest.raises(SystemExit) as exc:
        download_works.assign_output_folders(["rice", "rice!"])

    assert exc.value.code == 1
    error = capsys.readouterr().err
    assert "rice" in error
    assert "rice!" in error
