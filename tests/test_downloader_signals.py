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


def test_sort_mismatch_does_not_resume(tmp_path):
    """A cursor from another sort order must not be reused."""
    CheckpointManager(tmp_path).create(
        filter_str="publication_year:>2019",
        content_format="pdf",
        sort=None,
    )
    config = DownloadConfig(
        api_key="test",
        output_path=str(tmp_path),
        filter_str="publication_year:>2019",
        content_format=ContentFormat.PDF,
        sort="publication_date:desc",
        workers=1,
    )
    orchestrator = DownloadOrchestrator(config)

    asyncio.run(orchestrator.run())

    assert orchestrator.checkpoint_conflict is True
    assert orchestrator.checkpoint_manager.get().sort is None


def test_max_works_stops_before_the_next_page(tmp_path):
    """A cap keeps the cursor on the current page so a higher cap can resume."""
    from openalex_cli.api_client import WorkItem

    config = DownloadConfig(
        api_key="test",
        output_path=str(tmp_path),
        max_works=2,
        workers=1,
    )
    orchestrator = DownloadOrchestrator(config)
    orchestrator.checkpoint_manager.create(filter_str=None, content_format="pdf")
    orchestrator._work_queue = asyncio.Queue()
    calls = 0

    async def fake_list_works(**kwargs):
        nonlocal calls
        calls += 1
        yield [
            WorkItem(work_id="W1"),
            WorkItem(work_id="W2"),
            WorkItem(work_id="W3"),
        ], "next-page"

    orchestrator.api_client.list_works = fake_list_works  # type: ignore[method-assign]

    asyncio.run(orchestrator._produce_work())

    queued = []
    while not orchestrator._work_queue.empty():
        queued.append(orchestrator._work_queue.get_nowait().work_id)

    assert queued == ["W1", "W2"]
    assert calls == 1
    assert orchestrator.checkpoint_manager.get().current_cursor == "*"


def test_max_works_counts_papers_already_saved(tmp_path):
    """Saved papers fill the cap, so a rerun does not queue another batch."""
    from openalex_cli.api_client import WorkItem

    config = DownloadConfig(
        api_key="test",
        output_path=str(tmp_path),
        max_works=2,
        workers=1,
    )
    orchestrator = DownloadOrchestrator(config)
    orchestrator.checkpoint_manager.create(filter_str=None, content_format="pdf")
    orchestrator.checkpoint_manager.mark_completed("W1", file_size=1, credits=1)
    orchestrator.checkpoint_manager.mark_completed("W2", file_size=1, credits=1)
    orchestrator._work_queue = asyncio.Queue()
    calls = 0

    async def fake_list_works(**kwargs):
        nonlocal calls
        calls += 1
        yield [WorkItem(work_id="W3")], "next-page"

    orchestrator.api_client.list_works = fake_list_works  # type: ignore[method-assign]

    asyncio.run(orchestrator._produce_work())

    assert calls == 0
    assert orchestrator._work_queue.empty()
    assert orchestrator.checkpoint_manager.get().current_cursor == "*"


def test_max_works_retries_a_failed_save_when_the_page_ends_on_the_cap(tmp_path):
    """A page that fills the cap stays put so a failed save is retried."""
    from openalex_cli.api_client import WorkItem

    config = DownloadConfig(
        api_key="test",
        output_path=str(tmp_path),
        max_works=2,
        workers=1,
    )
    orchestrator = DownloadOrchestrator(config)
    orchestrator.checkpoint_manager.create(filter_str=None, content_format="pdf")
    orchestrator._work_queue = asyncio.Queue()

    async def fake_list_works(**kwargs):
        if kwargs.get("cursor") != "*":
            yield [WorkItem(work_id="W9")], "later"
            return
        yield [WorkItem(work_id="W1"), WorkItem(work_id="W2")], "next-page"

    orchestrator.api_client.list_works = fake_list_works  # type: ignore[method-assign]

    asyncio.run(orchestrator._produce_work())
    assert orchestrator.checkpoint_manager.get().current_cursor == "*"

    orchestrator.checkpoint_manager.mark_completed("W1", file_size=1, credits=1)
    orchestrator._work_queue = asyncio.Queue()
    asyncio.run(orchestrator._produce_work())

    queued = []
    while not orchestrator._work_queue.empty():
        queued.append(orchestrator._work_queue.get_nowait().work_id)

    assert queued == ["W2"]
    assert orchestrator.checkpoint_manager.get().current_cursor == "*"


def test_max_works_advances_when_the_page_is_under_the_cap(tmp_path):
    from openalex_cli.api_client import WorkItem

    config = DownloadConfig(
        api_key="test",
        output_path=str(tmp_path),
        max_works=5,
        workers=1,
    )
    orchestrator = DownloadOrchestrator(config)
    orchestrator.checkpoint_manager.create(filter_str=None, content_format="pdf")
    orchestrator._work_queue = asyncio.Queue()

    async def fake_list_works(**kwargs):
        yield [WorkItem(work_id="W1"), WorkItem(work_id="W2")], "next-page"

    orchestrator.api_client.list_works = fake_list_works  # type: ignore[method-assign]

    asyncio.run(orchestrator._produce_work())

    assert orchestrator.checkpoint_manager.get().current_cursor == "next-page"


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
