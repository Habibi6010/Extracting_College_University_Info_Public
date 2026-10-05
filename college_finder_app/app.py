"""Flask app: serves the college finder page and its JSON API."""
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

from backend import cache, field_catalog, scorecard, staff_jobs

load_dotenv()

app = Flask(__name__)

_catalog = field_catalog.load_catalog()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/states")
def api_states():
    return jsonify(scorecard.list_states())


@app.route("/api/fields")
def api_fields():
    return jsonify(_catalog)


@app.route("/api/colleges")
def api_colleges():
    state_param = request.args.get("state", "")
    fields_param = request.args.get("fields", "")
    refresh = request.args.get("refresh") == "1"

    try:
        state_abbr = scorecard.normalize_state(state_param)
    except ValueError:
        return jsonify({"error": f"Unknown state: {state_param!r}"}), 400

    requested_fields = [f for f in fields_param.split(",") if f]
    if not requested_fields:
        return jsonify({"error": "No fields requested"}), 400

    school_cache = cache.load(state_abbr)
    needs_fetch = refresh or bool(cache.missing_fields(school_cache, requested_fields))

    if needs_fetch:
        api_key = os.environ.get("SCORECARD_API_KEY")
        if not api_key:
            return jsonify({"error": "SCORECARD_API_KEY is not set"}), 502
        try:
            rows = scorecard.fetch_schools(state_abbr, requested_fields, api_key)
        except Exception as exc:
            app.logger.exception("College Scorecard request failed")
            safe_message = str(exc).replace(api_key, "***")
            return jsonify({"error": f"College Scorecard request failed: {safe_message}"}), 502
        school_cache = cache.merge_rows(school_cache, requested_fields, rows)
        cache.save(state_abbr, school_cache)

    schools = cache.rows_for_fields(school_cache, requested_fields)
    schools = [field_catalog.decode_row(s, _catalog) for s in schools]

    return jsonify({"state": state_abbr, "count": len(schools), "schools": schools})


@app.route("/api/staff/find", methods=["POST"])
def api_staff_find():
    body = request.get_json(silent=True) or {}
    schools = body.get("schools") or []
    if not schools:
        return jsonify({"error": "No schools provided"}), 400
    refresh = bool(body.get("refresh"))
    job_id = staff_jobs.start_job(schools, refresh=refresh, run_in_thread=not app.testing)
    return jsonify({"job_id": job_id}), 202


@app.route("/api/staff/status/<job_id>")
def api_staff_status(job_id):
    status = staff_jobs.get_status(job_id)
    if status is None:
        return jsonify({"error": "Unknown job_id"}), 404
    return jsonify(status)


if __name__ == "__main__":
    app.run(debug=False, port=5000)
