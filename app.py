"""
Flask API backend for the Exam Result Summarizer web UI.
Endpoints consumed by the single-page React frontend.
"""

import os
import json
import logging
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from processor import (
    parse_marks_content,
    compute_summary,
    generate_all_feedback,
    notify_all,
    build_report,
    THRESHOLDS,
)
from dataclasses import asdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
app = Flask(__name__, static_folder="static", static_url_path="")
CORS(app)


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/process", methods=["POST"])
def process():
    """
    Accepts:
      - file: CSV marks sheet (multipart/form-data)
      - api_key: Anthropic API key
      - distinction_min: override threshold (optional)
      - pass_min: override threshold (optional)
      - notify_channel: email | whatsapp | both | none
    Returns full analysis JSON.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    csv_content = file.read().decode("utf-8")

    api_key = request.form.get("api_key", os.environ.get("ANTHROPIC_API_KEY", ""))
    if not api_key:
        return jsonify({"error": "Anthropic API key required"}), 400

    # Optional threshold overrides
    cfg = dict(THRESHOLDS)
    try:
        if "distinction_min" in request.form:
            cfg["distinction_min"] = float(request.form["distinction_min"])
        if "pass_min" in request.form:
            cfg["pass_min"] = float(request.form["pass_min"])
    except ValueError:
        return jsonify({"error": "Invalid threshold values"}), 400

    notify_channel = request.form.get("notify_channel", "both")

    try:
        students = parse_marks_content(csv_content)
        if not students:
            return jsonify({"error": "No valid student records found in CSV"}), 400

        # Re-classify with custom thresholds if provided
        from processor import classify
        for s in students:
            s.grade = classify(s.percentage, cfg)

        summary = compute_summary(students)
        students = generate_all_feedback(students, api_key)

        if notify_channel != "none":
            notify_all(students, channel=notify_channel)

        report = build_report(students, summary)
        return jsonify(report)

    except Exception as e:
        logging.exception("Processing error")
        return jsonify({"error": str(e)}), 500


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": "1.0.0"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
