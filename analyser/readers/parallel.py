"""Read the page layouts of a long statement on several processor cores.

Turning a PDF page into words and lines is by far the slowest step (about 0.7 s a page), and every
page is independent, so long statements are split between worker processes. Short ones are read
in the calling process, where starting workers would cost more than it saves.
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from analyser.readers.layout import PageGeometry, page_geometry
from analyser.unlock import open_statement

MIN_PAGES = 12  # shorter statements are not worth the worker start-up time
MAX_WORKERS = 8


def _read_pages(args: tuple) -> list[PageGeometry]:
    path, password, first, last, y_tolerance, use_text_flow = args
    with open_statement(path, password) as pdf:
        return [page_geometry(pdf.pages[i], y_tolerance, use_text_flow) for i in range(first, last)]


def page_geometries(path: str | Path, password: str | None, page_count: int,
                    y_tolerance: float = 3, use_text_flow: bool = False) -> list[PageGeometry] | None:
    """Layouts of every page in order, or None when the caller should read the pages itself."""
    workers = min(MAX_WORKERS, os.cpu_count() or 1, page_count // 4)
    if page_count < MIN_PAGES or workers < 2:
        return None
    step = -(-page_count // workers)  # ceil: one contiguous block of pages per worker
    jobs = [(str(path), password, a, min(a + step, page_count), y_tolerance, use_text_flow) for a in range(0, page_count, step)]
    try:
        with ProcessPoolExecutor(max_workers=len(jobs)) as pool:
            return [geo for block in pool.map(_read_pages, jobs) for geo in block]
    except Exception:  # a worker could not start or died: the slower single-process read still works
        return None
