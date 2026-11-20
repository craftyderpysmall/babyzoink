import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/site"))

from export import queue_jobs


def test_open_jobs_are_unassigned_and_keep_their_progress(tmp_path):
    queue = tmp_path / "STATUS.md"
    queue.write_text(
        "## Codex task queue\n"
        "| 1 | Finished job | handoff | no | done |\n"
        "| 2 | Unassigned job | handoff | no | open: tested by claude (claude) |\n"
        "| 3 | (claude) Assigned job | handoff | no | queued |\n"
        "## Active work\n",
        encoding="utf-8",
    )

    jobs = queue_jobs(queue)

    assert [job["number"] for job in jobs] == [3, 2, 1]
    assert jobs[1] == {"number": 2, "task": "Unassigned job", "owner": "Unassigned",
                       "status": "open", "progress": "open: tested by claude (claude)"}


def test_implemented_job_with_acceptance_work_remains_in_progress(tmp_path):
    queue = tmp_path / "STATUS.md"
    queue.write_text(
        "## Codex task queue\n"
        "| 46 | Launch fresh \\| keep | handoff | yes | implemented, acceptance tests pending |\n",
        encoding="utf-8",
    )

    assert queue_jobs(queue) == [
        {"number": 46, "task": "Launch fresh | keep", "owner": "Codex",
         "status": "in progress", "progress": "implemented, acceptance tests pending"},
    ]
