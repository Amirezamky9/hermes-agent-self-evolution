"""Tests for Reporter — no real subprocess calls for hermes/telegram."""
from unittest.mock import patch, MagicMock
import tempfile

from evolution.core.reporter import Reporter
from evolution.core.pipeline import PipelineResult
from evolution.core.cron_runner import NightlyReport


# ── Helpers ──────────────────────────────────────────────────────────────

def _mock_result(name, passed=False, error=None, improvement=0.0, patches=0,
                 version=None, gaps=0, safety=True):
    return PipelineResult(
        skill_name=name,
        passed=passed,
        error=error,
        improvement=improvement,
        patches_generated=patches,
        version_created=version,
        gaps_found=gaps,
        safety_passed=safety,
        old_score=0.5,
        new_score=0.5 + improvement,
        duration_seconds=12.0,
    )


# ── format_pipeline_result ──────────────────────────────────────────────

class TestFormatPipelineResult:
    def test_improved_skill(self):
        r = _mock_result("test-skill", passed=True, improvement=0.123,
                         patches=3, version="v1.2.0", gaps=2)
        msg = Reporter().format_pipeline_result(r)
        assert "test-skill" in msg
        assert "+12.3%" in msg
        assert "v1.2.0" in msg
        assert "✅" in msg
        assert "12s" in msg

    def test_no_change(self):
        r = _mock_result("n8n-patterns", passed=True, improvement=0.0)
        msg = Reporter().format_pipeline_result(r)
        assert "بدون تغییر" in msg
        assert "⏭️" in msg

    def test_error(self):
        r = _mock_result("broken", error="Step 'x' failed: boom")
        msg = Reporter().format_pipeline_result(r)
        assert "boom" in msg
        assert "❌" in msg

    def test_not_passed_no_error(self):
        r = _mock_result("unknown", passed=False)
        msg = Reporter().format_pipeline_result(r)
        assert "ناموفق" in msg
        assert "❌" in msg


# ── format_nightly_report ──────────────────────────────────────────────

class TestFormatNightlyReport:
    def test_basic_nightly(self):
        report = NightlyReport(
            timestamp="2026-07-24",
            skills_analyzed=3,
            skills_improved=2,
            skills_failed=0,
            total_versions=1,
            results=[
                _mock_result("a", passed=True, improvement=0.07),
                _mock_result("b", passed=True, improvement=0.045),
                _mock_result("c", passed=True, improvement=0.0),
            ],
        )
        msg = Reporter().format_nightly_report(report)
        assert "2026-07-24" in msg
        assert "3 تحلیل شد" in msg
        assert "✅ بهبود: 2 مهارت" in msg
        assert "+7.0%" in msg
        assert "+4.5%" in msg
        assert "بدون تغییر ⏭️" in msg
        assert "1 جدید" in msg

    def test_nightly_with_failures(self):
        report = NightlyReport(
            timestamp="2026-07-24",
            skills_analyzed=2,
            skills_improved=0,
            skills_failed=1,
            results=[
                _mock_result("ok", passed=True, improvement=0.0),
                _mock_result("bad", error="timeout"),
            ],
        )
        msg = Reporter().format_nightly_report(report)
        assert "خطا" in msg
        assert "timeout" in msg
        assert "1 شکست" in report.summary or "شکست" in msg


# ── save_to_mnemosyne ──────────────────────────────────────────────────

class TestSaveToMnemosyne:
    @patch("evolution.core.reporter.os.unlink")
    @patch("evolution.core.reporter.subprocess.run")
    @patch("evolution.core.reporter.tempfile.NamedTemporaryFile")
    def test_success(self, mock_tmp, mock_run, mock_unlink):
        mock_tmp.return_value.__enter__.return_value.name = "/tmp/test.md"
        mock_run.return_value = MagicMock(returncode=0)

        reporter = Reporter()
        assert reporter.save_to_mnemosyne("test report", "test-skill") is True
        mock_run.assert_called_once()

    @patch("evolution.core.reporter.subprocess.run", side_effect=FileNotFoundError)
    @patch("evolution.core.reporter.tempfile.NamedTemporaryFile")
    def test_hermes_not_found(self, mock_tmp, mock_run):
        mock_tmp.return_value.__enter__.return_value.name = "/tmp/test.md"
        reporter = Reporter()
        assert reporter.save_to_mnemosyne("test", "test-skill") is False


# ── deliver_telegram ───────────────────────────────────────────────────

class TestDeliverTelegram:
    @patch("evolution.core.reporter.subprocess.run")
    def test_skipped_no_chat_id(self, mock_run):
        reporter = Reporter()  # no chat_id
        assert reporter.deliver_telegram("hello") is False
        mock_run.assert_not_called()

    @patch("evolution.core.reporter.subprocess.run")
    def test_success_with_chat_id(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        reporter = Reporter(telegram_chat_id="12345")
        assert reporter.deliver_telegram("hello") is True
        mock_run.assert_called_once()

    @patch("evolution.core.reporter.subprocess.run", side_effect=FileNotFoundError)
    def test_hermes_missing(self, mock_run):
        reporter = Reporter(telegram_chat_id="12345")
        assert reporter.deliver_telegram("hello") is False
