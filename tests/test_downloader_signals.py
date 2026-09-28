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

    assert orchestrator.checkpoint_manager.get().filter_str == "publication_year:2019"
