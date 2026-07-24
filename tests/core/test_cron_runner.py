"""Tests for CronRunner — uses mock data, no real LLM or cron."""

from unittest.mock import patch, MagicMock
from evolution.core.cron_runner import CronRunner, NightlyReport
from evolution.core.pipeline import PipelineResult


def _mock_result(name, passed=False, error=None, improvement=0.0, patches=0, version=None):
    return PipelineResult(
        skill_name=name,
        passed=passed,
        error=error,
        improvement=improvement,
        patches_generated=patches,
        version_created=version,
        old_score=0.5,
        new_score=0.5 + improvement,
    )


class TestNightlyReport:
    def test_dataclass_defaults(self):
        r = NightlyReport()
        assert r.skills_analyzed == 0
        assert r.results == []


class TestCronRunnerInit:
    def test_default_config(self):
        cr = CronRunner()
        assert cr.config is not None
        assert cr.skills == []
        assert cr.pipeline is not None

    def test_custom_skills(self):
        cr = CronRunner(skills=["foo", "bar"])
        assert cr.skills == ["foo", "bar"]


class TestGenerateReport:
    def test_empty_results(self):
        cr = CronRunner()
        report = cr.generate_report([])
        assert "0 تحلیل شد" in report
        assert "جزئیات:" in report

    def test_improved_skill(self):
        cr = CronRunner()
        results = [_mock_result("n8n-patterns", passed=True, improvement=0.12, patches=2, version="1.0")]
        report = cr.generate_report(results)
        assert "n8n-patterns" in report
        assert "+12% بهبود ✅" in report

    def test_no_change_skill(self):
        cr = CronRunner()
        results = [_mock_result("research-manager", passed=True, improvement=0.0)]
        report = cr.generate_report(results)
        assert "بدون تغییر ⏭️" in report

    def test_failed_skill(self):
        cr = CronRunner()
        results = [_mock_result("broken-skill", error="Step 'x' failed: boom")]
        report = cr.generate_report(results)
        assert "broken-skill" in report
        assert "خطا ❌" in report

    def test_counts(self):
        cr = CronRunner()
        results = [
            _mock_result("a", passed=True, improvement=0.05, version="1.0"),
            _mock_result("b", passed=False, error="fail"),
            _mock_result("c", passed=True, improvement=0.0),
        ]
        report = cr.generate_report(results)
        assert "3 تحلیل شد" in report
        assert "2 مهارت بهتر شد" in report
        assert "1 مهارت خراب شد" in report
        assert "1 نسخه جدید ذخیره شد" in report


class TestRunNightly:
    @patch.object(CronRunner, "run_skill")
    def test_aggregates_results(self, mock_run_skill):
        mock_run_skill.side_effect = [
            _mock_result("a", passed=True, improvement=0.1, version="1.0"),
            _mock_result("b", passed=True, improvement=0.0),
        ]
        cr = CronRunner(skills=["a", "b"])
        report = cr.run_nightly()

        assert report.skills_analyzed == 2
        assert report.skills_improved == 2
        assert report.total_versions == 1
        assert "2 تحلیل شد" in report.summary

    @patch.object(CronRunner, "run_skill")
    def test_empty_skills(self, mock_run_skill):
        cr = CronRunner(skills=[])
        report = cr.run_nightly()
        assert report.skills_analyzed == 0
        assert mock_run_skill.call_count == 0


class TestRunSkill:
    @patch("evolution.core.cron_runner.Pipeline.run")
    def test_delegates_to_pipeline(self, mock_pipeline_run):
        expected = _mock_result("test-skill", passed=True)
        mock_pipeline_run.return_value = expected

        cr = CronRunner()
        result = cr.run_skill("test-skill")

        mock_pipeline_run.assert_called_once_with("test-skill")
        assert result.skill_name == "test-skill"


class TestSaveToMemory:
    @patch("evolution.core.cron_runner.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        cr = CronRunner()
        assert cr.save_to_memory("test report") is True
        mock_run.assert_called_once()

    @patch("evolution.core.cron_runner.subprocess.run", side_effect=FileNotFoundError)
    def test_hermes_not_found(self, mock_run):
        cr = CronRunner()
        assert cr.save_to_memory("test report") is False
