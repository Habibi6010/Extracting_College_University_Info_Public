# college_finder_app/backend/staff_jobs.py
"""In-memory background job tracking for staff-lookup batches. Each job
processes its schools sequentially, checking the per-school cache first
unless refresh=True, and accumulates results so a status poll can render
them incrementally."""
import os
import threading
import uuid

from backend import staff_cache, staff_finder

_jobs = {}
_lock = threading.Lock()


def start_job(schools, refresh=False, run_in_thread=True):
    """Register a new job for `schools` (each {'name', 'state'}) and start
    processing them. Returns the new job_id immediately. If run_in_thread
    is False, processing happens synchronously before this function
    returns (used by tests and by Flask's TESTING mode to avoid real
    threads)."""
    job_id = uuid.uuid4().hex
    with _lock:
        _jobs[job_id] = {"done": 0, "total": len(schools), "results": [], "finished": False}

    if run_in_thread:
        threading.Thread(target=_run_job, args=(job_id, schools, refresh), daemon=True).start()
    else:
        _run_job(job_id, schools, refresh)

    return job_id


def get_status(job_id):
    """Return a copy of the job's current state, or None if job_id is
    unknown."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return None
        return dict(job, results=list(job["results"]))


def _run_job(job_id, schools, refresh):
    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    try:
        for school in schools:
            name = school.get("name", "") if isinstance(school, dict) else ""
            state_abbr = school.get("state", "") if isinstance(school, dict) else ""

            try:
                if not name:
                    raise ValueError("school entry is missing a 'name'")
                cached = None if refresh else staff_cache.load(state_abbr, name)
                if staff_cache.is_usable(cached):
                    staff_rows = cached["staff"]
                else:
                    result = staff_finder.find_staff_for_school(name, state_abbr, tavily_key)
                    staff_rows = result["staff"]
                    if not staff_cache.is_error_only(staff_rows):
                        staff_cache.save(state_abbr, name, staff_rows)
            except Exception as exc:
                staff_rows = [{
                    "name": "", "title": "", "category": "error", "sport": "",
                    "email": "", "phone": "", "source_url": "", "bio_url": "", "notes": str(exc),
                }]

            rows_with_school = [dict(row, school_name=name, state=state_abbr) for row in staff_rows]

            with _lock:
                job = _jobs[job_id]
                job["results"].extend(rows_with_school)
                job["done"] += 1
    finally:
        with _lock:
            _jobs[job_id]["finished"] = True
