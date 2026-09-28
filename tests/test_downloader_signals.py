"""Shutdown signal handlers are optional on platforms that lack them."""

import asyncio

from openalex_cli.checkpoint import CheckpointManager
from openalex_cli.downloader import DownloadConfig, DownloadOrchestrator
from openalex_cli.utils import ContentFormat


class _RecordingLoop:
    def __init__(self, implemented: bool) -> None:
        self.implemented = implemented
        self.added: list[int] = []
        self.removed: list[int] = []

    def add_signal_handler(self, sig: int, callback) -> None:
        if not self.implemented:
            raise NotImplementedError
        self.added.append(sig)

    def remove_signal_handler(self, sig: int) -> None:
        self.removed.append(sig)


def _orchestrator(tmp_path) -> DownloadOrchestrator:
    config = DownloadConfig(
        api_key="test",
        output_path=str(tmp_path),
        workers=1,
    )
    return DownloadOrchestrator(config)


def test_skips_unimplemented_signal_handlers(tmp_path):
    orchestrator = _orchestrator(tmp_path)
    loop = _RecordingLoop(implemented=False)

    installed = orchestrator._install_shutdown_handlers(loop)  # type: ignore[arg-type]
    orchestrator._remove_shutdown_handlers(loop, installed)  # type: ignore[arg-type]

    assert installed == []
    assert loop.added == []
    assert loop.removed == []


def test_removes_only_installed_signal_handlers(tmp_path):
    orchestrator = _orchestrator(tmp_path)
    loop = _RecordingLoop(implemented=True)

    installed = orchestrator._install_shutdown_handlers(loop)  # type: ignore[arg-type]
    orchestrator._remove_shutdown_handlers(loop, installed)  # type: ignore[arg-type]

    assert loop.added
    assert loop.removed == loop.added


def test_run_starts_when_signal_handlers_unsupported(tmp_path):
    """A mismatched checkpoint returns before any download, including on Windows."""
    CheckpointManager(tmp_path).create(
        filter_str="publication_year:2019",
        content_format="pdf",
    )
    config = DownloadConfig(
        api_key="test",
        output_path=str(tmp_path),
        filter_str="publication_year:>2019",
        content_format=ContentFormat.PDF,
        workers=1,
    )
    orchestrator = DownloadOrchestrator(config)

    asyncio.run(orchestrator.run())

    assert orchestrator.checkpoint_conflict is True
    assert orchestrator.checkpoint_manager.get().filter_str == "publication_year:2019"


def test_output_path_follows_publication_date_when_by_date(tmp_path):
    config = DownloadConfig(
        api_key="test",
        output_path=str(tmp_path),
        by_date=True,
        workers=1,
    )
    orchestrator = DownloadOrchestrator(config)

    path = orchestrator._output_path("W1", "pdf", "2024-09-11")

    assert path.as_posix() == "202409/11/W1.pdf"


def test_output_path_stays_flat_without_by_date(tmp_path):
    orchestrator = _orchestrator(tmp_path)

    path = orchestrator._output_path("W1", "pdf", "2024-09-11")

    assert path.as_posix() == "W1.pdf"


def test_by_date_skips_flat_directory_warning(tmp_path):
    config = DownloadConfig(
        api_key="test",
        output_path=str(tmp_path),
        by_date=True,
        workers=1,
    )
    orchestrator = DownloadOrchestrator(config)

    assert orchestrator._needs_flat_directory_warning(10001, already_warned=False) is False


def test_flat_directory_warning_for_large_flat_download(tmp_path):
    orchestrator = _orchestrator(tmp_path)

    assert orchestrator._needs_flat_directory_warning(10001, already_warned=False) is True
    assert orchestrator._needs_flat_directory_warning(10000, already_warned=False) is False


def test_nested_skips_flat_directory_warning(tmp_path):
    config = DownloadConfig(
        api_key="test",
        output_path=str(tmp_path),
        nested=True,
        workers=1,
    )
    orchestrator = DownloadOrchestrator(config)

    assert orchestrator._needs_flat_directory_warning(10001, already_warned=False) is False
