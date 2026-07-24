"""Reporter — formats PipelineResults/NightlyReports into Telegram-ready
Persian markdown, saves to Mnemosyne, and delivers to Telegram.

Usage:
    reporter = Reporter(telegram_chat_id="123456")
    msg = reporter.format_pipeline_result(result)
    reporter.save_to_mnemosyne(msg, result.skill_name)
    reporter.deliver_telegram(msg)
"""
import os
import subprocess
import tempfile
from typing import Optional

from evolution.core.cron_runner import NightlyReport
from evolution.core.pipeline import PipelineResult

# ponytail: no direct hermes API; subprocess to hermes CLI + curl.
# Replace with hermes SDK calls when a stable Python SDK exists.


def _severity_label(severity: str) -> str:
    labels = {"light": "سبک", "moderate": "متوسط", "heavy": "سنگین"}
    return labels.get(severity, severity)


class Reporter:
    def __init__(self, telegram_chat_id: Optional[str] = None):
        self.telegram_chat_id = telegram_chat_id

    # ── Formatting ────────────────────────────────────────────────────
    def format_pipeline_result(self, result: PipelineResult) -> str:
        """Single-skill optimization report in Persian."""
        # Score display: Pipeline stores as 0-1, show as percentage
        old_pct = result.old_score * 100
        new_pct = result.new_score * 100
        imp_pct = result.improvement * 100

        if result.passed and result.improvement > 0:
            change_line = f"✅ بهبود: +{imp_pct:.1f}%"
        elif result.passed:
            change_line = "⏭️ بدون تغییر"
        elif result.error:
            change_line = f"❌ خطا: {result.error[:80]}"
        else:
            change_line = "❌ ناموفق"

        version_line = f"📦 نسخه: {result.version_created}" if result.version_created else "📦 نسخه: —"

        lines = [
            "📊 گزارش بهینه‌سازی Skill",
            "━━━━━━━━━━━━━━━━━━━━",
            f"🔹 Skill: {result.skill_name}",
            f"📈 امتیاز قدیم: {old_pct:.1f}%",
            f"📈 امتیاز جدید: {new_pct:.1f}%",
            change_line,
            f"🏗️ خلأها: {result.gaps_found} | وصله‌ها: {result.patches_generated}",
            f"🛡️ ایمنی: {'✅' if result.safety_passed else '❌'}",
            version_line,
            f"⏱️ زمان: {result.duration_seconds:.0f}s",
            "━━━━━━━━━━━━━━━━━━━━",
        ]
        return "\n".join(lines)

    def format_nightly_report(self, report: NightlyReport) -> str:
        """Multi-skill nightly summary in Persian."""
        improved = report.skills_improved
        failed = report.skills_failed
        analyzed = report.skills_analyzed

        lines = [
            "📊 گزارش شبانه Skill Optimizer",
            "━━━━━━━━━━━━━━━━━━━━",
            f"📅 تاریخ: {report.timestamp}",
            f"🔢 مهارت‌ها: {analyzed} تحلیل شد",
            f"✅ بهبود: {improved} مهارت",
            f"❌ شکست: {failed} مهارت",
            f"📦 نسخه: {report.total_versions} جدید",
            "",
            "جزئیات:",
        ]

        for r in report.results:
            if r.error:
                lines.append(f"- {r.skill_name}: خطا ❌ ({r.error[:60]})")
            elif r.passed and r.improvement > 0:
                pct = f"+{r.improvement * 100:.1f}%"
                lines.append(f"- {r.skill_name}: {pct} ✅")
            elif r.passed:
                lines.append(f"- {r.skill_name}: بدون تغییر ⏭️")
            else:
                lines.append(f"- {r.skill_name}: ناموفق ❌")

        return "\n".join(lines)

    # ── Mnemosyne storage ─────────────────────────────────────────────
    def save_to_mnemosyne(self, report: str, skill_name: str) -> bool:
        """Store report in mnemosyne via hermes memory CLI. Returns True on success."""
        try:
            # Write to temp file to avoid shell-escaping issues
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False, encoding="utf-8"
            ) as f:
                f.write(report)
                tmp_path = f.name
            try:
                result = subprocess.run(
                    [
                        "hermes", "memory", "add",
                        "--target", "memory",
                        "--content", f"$(cat {tmp_path})",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                return result.returncode == 0
            finally:
                os.unlink(tmp_path)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    # ── Telegram delivery ─────────────────────────────────────────────
    def deliver_telegram(self, message: str) -> bool:
        """Send message to Telegram via hermes send-message or curl.
        Returns True on success. Skips silently if no chat_id configured."""
        if not self.telegram_chat_id:
            return False
        try:
            result = subprocess.run(
                [
                    "hermes", "send-message",
                    "--chat-id", self.telegram_chat_id,
                    "--message", message,
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
