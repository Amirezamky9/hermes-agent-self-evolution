"""CronRunner — orchestrates nightly optimization runs and generates reports."""

import subprocess
import datetime
from dataclasses import dataclass, field
from typing import Optional

from evolution.core.config import EvolutionConfig
from evolution.core.pipeline import Pipeline, PipelineResult


@dataclass
class NightlyReport:
    timestamp: str = ""
    skills_analyzed: int = 0
    skills_improved: int = 0
    skills_failed: int = 0
    total_patches: int = 0
    total_versions: int = 0
    summary: str = ""
    results: list = field(default_factory=list)


class CronRunner:
    """Orchestrates the nightly optimization run for configured skills."""

    def __init__(self, config: Optional[EvolutionConfig] = None, skills: Optional[list[str]] = None):
        self.config = config or EvolutionConfig()
        self.skills = skills or []
        self.pipeline = Pipeline(config=self.config)

    def run_nightly(self) -> NightlyReport:
        """Run the full nightly optimization for all configured skills."""
        report = NightlyReport(timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
        results: list[PipelineResult] = []

        for skill_name in self.skills:
            result = self.run_skill(skill_name)
            results.append(result)

        report.results = results
        report.skills_analyzed = len(results)
        report.skills_improved = sum(1 for r in results if r.passed)
        report.skills_failed = sum(1 for r in results if r.error is not None)
        report.total_patches = sum(r.patches_generated for r in results)
        report.total_versions = sum(1 for r in results if r.version_created is not None)
        report.summary = self.generate_report(results)
        return report

    def run_skill(self, skill_name: str) -> PipelineResult:
        """Run the optimization pipeline for a single skill."""
        return self.pipeline.run(skill_name)

    def generate_report(self, results: list[PipelineResult]) -> str:
        """Generate a markdown report string from pipeline results.

        Language: Persian (Farsi) for Telegram delivery.
        """
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        analyzed = len(results)
        improved = sum(1 for r in results if r.passed)
        failed = sum(1 for r in results if r.error is not None)
        versions = sum(1 for r in results if r.version_created is not None)

        lines = [
            "📊 گزارش شبانه Skill Optimizer",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"تاریخ: {now}",
            f"مهارت‌ها: {analyzed} تحلیل شد",
            f"بهبود: {improved} مهارت بهتر شد",
            f"شکست: {failed} مهارت خراب شد",
            f"نسخه‌ها: {versions} نسخه جدید ذخیره شد",
            "",
            "جزئیات:",
        ]

        for r in results:
            if r.error:
                lines.append(f"- {r.skill_name}: خطا ❌ ({r.error})")
            elif r.passed and r.improvement > 0:
                pct = f"+{r.improvement * 100:.0f}%"
                lines.append(f"- {r.skill_name}: {pct} بهبود ✅")
            elif r.passed:
                lines.append(f"- {r.skill_name}: بدون تغییر ⏭️")
            else:
                lines.append(f"- {r.skill_name}: ناموفق ❌")

        return "\n".join(lines)

    def save_to_memory(self, report: str) -> bool:
        """Store report in mnemosyne via hermes memory CLI. Returns True on success."""
        try:
            # Use hermes memory add to store the nightly report
            result = subprocess.run(
                ["hermes", "memory", "add", "--text", report, "--tag", "skill-optimizer-nightly"],
                capture_output=True, text=True, timeout=30,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
