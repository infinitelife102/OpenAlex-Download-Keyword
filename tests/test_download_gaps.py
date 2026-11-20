"""Gap detection for papers saved with only metadata or only a PDF."""

from download_works import missing_pairs


def test_missing_pairs_finds_json_without_pdf_and_pdf_without_json(tmp_path):
    day = tmp_path / "202409" / "11"
    day.mkdir(parents=True)
    (day / "W1.json").write_text("{}", encoding="utf-8")
    (day / "W2.json").write_text("{}", encoding="utf-8")
    (day / "W2.pdf").write_bytes(b"%PDF")
    (day / "W3.pdf").write_bytes(b"%PDF")
    (tmp_path / ".openalex-checkpoint.json").write_text("{}", encoding="utf-8")

    json_only, pdf_only = missing_pairs(tmp_path)

    assert [path.name for path in json_only] == ["W1.json"]
    assert [path.name for path in pdf_only] == ["W3.pdf"]


def test_missing_pairs_is_empty_when_folder_is_absent(tmp_path):
    assert missing_pairs(tmp_path / "hydropower") == ([], [])
