"""
Exam Result Summarizer + Notifier
SAIT Evaluation Test - Scenario C
"""

import csv
import json
import os
import io
import logging
from datetime import datetime
from dataclasses import dataclass, asdict, field
from typing import Optional
import anthropic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)


# ─── Configuration ────────────────────────────────────────────────────────────

THRESHOLDS = {
    "distinction_min": 85,   # >= 85% → Distinction
    "pass_min": 50,           # >= 50% → Pass
                              # <  50% → Fail
}


# ─── Data Models ──────────────────────────────────────────────────────────────

@dataclass
class Student:
    student_name: str
    roll_no: str
    email: str
    subject: str
    marks_obtained: float
    total_marks: float
    percentage: float = 0.0
    grade: str = ""
    feedback: str = ""

    def __post_init__(self):
        self.percentage = round((self.marks_obtained / self.total_marks) * 100, 2)
        self.grade = classify(self.percentage)


@dataclass
class ClassSummary:
    subject: str
    total_students: int
    distinctions: int
    passes: int
    failures: int
    pass_rate: float
    average_marks: float
    top_scorer: str
    top_score: float
    lowest_score: float
    generated_at: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))


# ─── Classification ───────────────────────────────────────────────────────────

def classify(percentage: float, cfg: dict = THRESHOLDS) -> str:
    if percentage >= cfg["distinction_min"]:
        return "Distinction"
    elif percentage >= cfg["pass_min"]:
        return "Pass"
    else:
        return "Fail"


# ─── CSV / Excel Parser ───────────────────────────────────────────────────────

def parse_marks_csv(filepath: str) -> list[Student]:
    students = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                s = Student(
                    student_name=row["student_name"].strip(),
                    roll_no=row["roll_no"].strip(),
                    email=row["email"].strip(),
                    subject=row["subject"].strip(),
                    marks_obtained=float(row["marks_obtained"]),
                    total_marks=float(row["total_marks"]),
                )
                students.append(s)
            except (KeyError, ValueError) as e:
                logger.warning(f"Skipping row {row} — {e}")
    logger.info(f"Parsed {len(students)} students from {filepath}")
    return students


def parse_marks_content(content: str) -> list[Student]:
    """Parse CSV content from a string (for web API use)."""
    students = []
    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        try:
            s = Student(
                student_name=row["student_name"].strip(),
                roll_no=row["roll_no"].strip(),
                email=row.get("email", f"{row['roll_no'].strip().lower()}@university.edu").strip(),
                subject=row["subject"].strip(),
                marks_obtained=float(row["marks_obtained"]),
                total_marks=float(row["total_marks"]),
            )
            students.append(s)
        except (KeyError, ValueError) as e:
            logger.warning(f"Skipping row {row} — {e}")
    return students


# ─── Statistics ───────────────────────────────────────────────────────────────

def compute_summary(students: list[Student]) -> ClassSummary:
    if not students:
        raise ValueError("No students to summarize")

    subject = students[0].subject
    total = len(students)
    distinctions = sum(1 for s in students if s.grade == "Distinction")
    passes = sum(1 for s in students if s.grade == "Pass")
    failures = sum(1 for s in students if s.grade == "Fail")
    pass_rate = round(((distinctions + passes) / total) * 100, 1)
    avg = round(sum(s.percentage for s in students) / total, 1)
    top = max(students, key=lambda s: s.percentage)
    low = min(students, key=lambda s: s.percentage)

    return ClassSummary(
        subject=subject,
        total_students=total,
        distinctions=distinctions,
        passes=passes,
        failures=failures,
        pass_rate=pass_rate,
        average_marks=avg,
        top_scorer=top.student_name,
        top_score=top.percentage,
        lowest_score=low.percentage,
    )


# ─── LLM Feedback Generation ──────────────────────────────────────────────────

def generate_feedback_for_grade(
    client: anthropic.Anthropic,
    grade: str,
    subject: str,
    percentage: float,
) -> str:
    prompt = f"""You are a caring academic advisor writing a brief, personalized feedback message 
for a student who just received their exam results.

Subject: {subject}
Score: {percentage}%
Grade: {grade}

Write a warm, encouraging 2-3 sentence feedback message appropriate for this student's grade.
- Distinction (>=85%): Celebrate their achievement, encourage them to mentor peers or aim higher.
- Pass (50-84%): Acknowledge their effort, highlight room for improvement, stay motivating.
- Fail (<50%): Be empathetic and supportive, suggest specific next steps (office hours, revision), never harsh.

Keep it personal, positive, and actionable. Do NOT start with "Dear Student" or generic openers.
Output ONLY the feedback message, nothing else."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text.strip()


def generate_all_feedback(students: list[Student], api_key: str) -> list[Student]:
    client = anthropic.Anthropic(api_key=api_key)

    # Cache by grade+subject to avoid redundant API calls
    grade_cache: dict[str, str] = {}

    for student in students:
        cache_key = f"{student.grade}::{student.subject}::{int(student.percentage // 10) * 10}"
        if cache_key not in grade_cache:
            logger.info(f"Generating feedback for {student.grade} grade ({student.percentage}%)")
            grade_cache[cache_key] = generate_feedback_for_grade(
                client, student.grade, student.subject, student.percentage
            )
        student.feedback = grade_cache[cache_key]

    return students


# ─── Notification Simulator ────────────────────────────────────────────────────

NOTIFICATION_LOG = []


def simulate_email(student: Student) -> dict:
    subject_line = {
        "Distinction": f"🏆 Outstanding! Your {student.subject} Exam Result",
        "Pass": f"✅ Your {student.subject} Exam Result",
        "Fail": f"📋 Important: Your {student.subject} Exam Result & Next Steps",
    }[student.grade]

    body = f"""To: {student.email}
Subject: {subject_line}

Dear {student.student_name},

We hope this message finds you well. Your results for {student.subject} are now available.

  Roll No   : {student.roll_no}
  Marks     : {student.marks_obtained}/{student.total_marks}
  Percentage: {student.percentage}%
  Grade     : {student.grade}

{student.feedback}

Best regards,
Examination Department
"""
    log_entry = {
        "channel": "EMAIL",
        "to": student.email,
        "name": student.student_name,
        "grade": student.grade,
        "subject_line": subject_line,
        "timestamp": datetime.now().isoformat(),
        "status": "SENT (simulated)",
    }
    NOTIFICATION_LOG.append(log_entry)
    logger.info(f"[EMAIL] → {student.email} ({student.grade})")
    return {"body": body, "log": log_entry}


def simulate_whatsapp(student: Student) -> dict:
    emoji = {"Distinction": "🏆", "Pass": "✅", "Fail": "📋"}[student.grade]
    message = (
        f"{emoji} *Exam Result — {student.subject}*\n\n"
        f"Hi {student.student_name.split()[0]}!\n"
        f"Roll No: {student.roll_no}\n"
        f"Marks: {student.marks_obtained}/{student.total_marks} ({student.percentage}%)\n"
        f"Grade: *{student.grade}*\n\n"
        f"{student.feedback}"
    )
    log_entry = {
        "channel": "WHATSAPP",
        "to": f"+92-XXX-XXXXXXX ({student.roll_no})",
        "name": student.student_name,
        "grade": student.grade,
        "timestamp": datetime.now().isoformat(),
        "status": "SENT (simulated)",
    }
    NOTIFICATION_LOG.append(log_entry)
    logger.info(f"[WHATSAPP] → {student.student_name} ({student.grade})")
    return {"message": message, "log": log_entry}


def notify_all(students: list[Student], channel: str = "both") -> list[dict]:
    results = []
    for student in students:
        if channel in ("email", "both"):
            results.append(simulate_email(student))
        if channel in ("whatsapp", "both"):
            results.append(simulate_whatsapp(student))
    return results


# ─── JSON Report Generator ────────────────────────────────────────────────────

def build_report(students: list[Student], summary: ClassSummary) -> dict:
    return {
        "generated_at": summary.generated_at,
        "thresholds": THRESHOLDS,
        "summary": asdict(summary),
        "students": [asdict(s) for s in students],
        "notification_log": NOTIFICATION_LOG,
    }


# ─── CLI Entry Point ──────────────────────────────────────────────────────────

def run_cli(filepath: str, api_key: str, notify: str = "both"):
    print("\n" + "=" * 60)
    print("  SAIT Exam Result Summarizer + Notifier")
    print("=" * 60 + "\n")

    students = parse_marks_csv(filepath)
    summary = compute_summary(students)

    print(f"📊 Class Summary — {summary.subject}")
    print(f"   Total Students : {summary.total_students}")
    print(f"   Distinctions   : {summary.distinctions}")
    print(f"   Passes         : {summary.passes}")
    print(f"   Failures       : {summary.failures}")
    print(f"   Pass Rate      : {summary.pass_rate}%")
    print(f"   Class Average  : {summary.average_marks}%")
    print(f"   Top Scorer     : {summary.top_scorer} ({summary.top_score}%)")
    print()

    print("🤖 Generating personalized feedback via Claude AI...")
    students = generate_all_feedback(students, api_key)
    print("✅ Feedback generated!\n")

    print("📨 Simulating notifications...\n")
    notify_all(students, channel=notify)

    print("\n📋 Per-Student Results:")
    print(f"{'Name':<22} {'Roll':<10} {'%':>6} {'Grade':<12} {'Notification'}")
    print("-" * 65)
    for s in students:
        print(f"{s.student_name:<22} {s.roll_no:<10} {s.percentage:>5.1f}% {s.grade:<12} ✉️ Sent")

    report = build_report(students, summary)
    out_path = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n✅ Full report saved → {out_path}")


if __name__ == "__main__":
    import sys
    filepath = sys.argv[1] if len(sys.argv) > 1 else "sample_marks.csv"
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("⚠️  Set ANTHROPIC_API_KEY environment variable")
        sys.exit(1)
    run_cli(filepath, api_key)
