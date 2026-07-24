"""Tests for ref_manager — uses temp directories with sample SKILL.md files."""
import pytest

from evolution.core.ref_manager import ReferenceManager, _extract_keywords


# --- Helpers ---

def _write_skill(skills_dir, name, description="", related=None, body=""):
    """Create a sample skill directory with SKILL.md."""
    d = skills_dir / name
    d.mkdir(parents=True, exist_ok=True)
    related_lines = ""
    if related:
        items = ", ".join(related)
        related_lines = f"\nrelated_skills: [{items}]"
    fm = f"---\nname: {name}\ndescription: {description}{related_lines}\n---\n"
    content = fm + (f"\n# {name}\n\n{body}" if body else "")
    (d / "SKILL.md").write_text(content)


# --- Tests ---

class TestScanReferences:
    def test_no_skills(self, tmp_path):
        rm = ReferenceManager(hermes_path=str(tmp_path))
        assert rm.scan_references() == []

    def test_skill_no_refs(self, tmp_path):
        skills = tmp_path / "skills"
        _write_skill(skills, "alpha", description="An alpha skill")
        rm = ReferenceManager(hermes_path=str(tmp_path))
        refs = rm.scan_references()
        assert len(refs) == 1
        assert refs[0]["skill_name"] == "alpha"
        assert refs[0]["related_skills"] == []
        assert refs[0]["broken_refs"] == []

    def test_valid_reference(self, tmp_path):
        skills = tmp_path / "skills"
        _write_skill(skills, "alpha", related=["beta"])
        _write_skill(skills, "beta")
        rm = ReferenceManager(hermes_path=str(tmp_path))
        refs = rm.scan_references()
        alpha = next(r for r in refs if r["skill_name"] == "alpha")
        assert alpha["related_skills"] == ["beta"]
        assert alpha["broken_refs"] == []

    def test_broken_reference(self, tmp_path):
        skills = tmp_path / "skills"
        _write_skill(skills, "alpha", related=["beta", "gamma"])
        _write_skill(skills, "beta")
        # gamma does not exist
        rm = ReferenceManager(hermes_path=str(tmp_path))
        refs = rm.scan_references()
        alpha = next(r for r in refs if r["skill_name"] == "alpha")
        assert alpha["broken_refs"] == ["gamma"]

    def test_multiple_refs_mixed(self, tmp_path):
        skills = tmp_path / "skills"
        _write_skill(skills, "alpha", related=["beta", "missing1", "missing2"])
        _write_skill(skills, "beta")
        rm = ReferenceManager(hermes_path=str(tmp_path))
        refs = rm.scan_references()
        alpha = next(r for r in refs if r["skill_name"] == "alpha")
        assert sorted(alpha["broken_refs"]) == ["missing1", "missing2"]


class TestFindBrokenReferences:
    def test_no_broken(self, tmp_path):
        skills = tmp_path / "skills"
        _write_skill(skills, "alpha", related=["beta"])
        _write_skill(skills, "beta")
        rm = ReferenceManager(hermes_path=str(tmp_path))
        assert rm.find_broken_references() == []

    def test_finds_broken(self, tmp_path):
        skills = tmp_path / "skills"
        _write_skill(skills, "alpha", related=["nonexistent"])
        rm = ReferenceManager(hermes_path=str(tmp_path))
        broken = rm.find_broken_references()
        assert len(broken) == 1
        assert broken[0] == {"skill_name": "alpha", "missing_ref": "nonexistent"}


class TestDetectOverlap:
    def test_no_overlap(self, tmp_path):
        skills = tmp_path / "skills"
        _write_skill(skills, "alpha", description="Machine learning")
        _write_skill(skills, "beta", description="Web scraping")
        rm = ReferenceManager(hermes_path=str(tmp_path))
        assert rm.detect_overlap() == []

    def test_similar_names(self, tmp_path):
        skills = tmp_path / "skills"
        _write_skill(skills, "web-scraping", description="Scrape websites")
        _write_skill(skills, "web-scrape", description="Scrape web pages")
        rm = ReferenceManager(hermes_path=str(tmp_path))
        overlaps = rm.detect_overlap()
        assert len(overlaps) == 1
        assert "similar names" in overlaps[0]["reason"]

    def test_similar_descriptions(self, tmp_path):
        skills = tmp_path / "skills"
        _write_skill(skills, "alpha", description="Deploy applications to kubernetes")
        _write_skill(skills, "beta", description="Deploy applications to docker")
        rm = ReferenceManager(hermes_path=str(tmp_path))
        overlaps = rm.detect_overlap()
        assert len(overlaps) == 1
        assert "similar descriptions" in overlaps[0]["reason"]

    def test_similar_body_content(self, tmp_path):
        skills = tmp_path / "skills"
        _write_skill(skills, "tool-a", description="A tool", body="run tests and deploy")
        _write_skill(skills, "tool-b", description="B tool", body="run tests and deploy")
        rm = ReferenceManager(hermes_path=str(tmp_path))
        overlaps = rm.detect_overlap()
        assert len(overlaps) == 1

    def test_sorted_by_score_desc(self, tmp_path):
        skills = tmp_path / "skills"
        _write_skill(skills, "deploy-app", description="Deploy web application to cloud")
        _write_skill(skills, "deploy-svc", description="Deploy web application to cloud")
        _write_skill(skills, "scrape", description="Scrape data from website")
        rm = ReferenceManager(hermes_path=str(tmp_path))
        overlaps = rm.detect_overlap()
        if len(overlaps) > 1:
            for i in range(len(overlaps) - 1):
                assert overlaps[i]["similarity_score"] >= overlaps[i + 1]["similarity_score"]


class TestSuggestMerges:
    def test_no_merges_when_no_overlap(self, tmp_path):
        skills = tmp_path / "skills"
        _write_skill(skills, "alpha", description="Perform numerical analysis")
        _write_skill(skills, "beta", description="Scrape web pages")
        rm = ReferenceManager(hermes_path=str(tmp_path))
        assert rm.suggest_merges() == []

    def test_merge_suggested_for_similar(self, tmp_path):
        skills = tmp_path / "skills"
        _write_skill(skills, "deploy-k8s", description="Deploy applications to kubernetes clusters and manage deployments")
        _write_skill(skills, "deploy-k8", description="Deploy applications to kubernetes clusters and manage deployments")
        rm = ReferenceManager(hermes_path=str(tmp_path))
        merges = rm.suggest_merges()
        assert len(merges) == 1
        merge = merges[0]
        assert merge["keep"] in ("deploy-k8s", "deploy-k8")
        assert merge["merge_into"] in ("deploy-k8s", "deploy-k8")
        assert merge["keep"] != merge["merge_into"]


class TestToReport:
    def test_no_issues(self, tmp_path):
        skills = tmp_path / "skills"
        _write_skill(skills, "alpha", description="Unique skill")
        rm = ReferenceManager(hermes_path=str(tmp_path))
        report = rm.to_report()
        assert "No issues detected" in report
        assert "Reference Report" in report

    def test_broken_in_report(self, tmp_path):
        skills = tmp_path / "skills"
        _write_skill(skills, "alpha", related=["ghost"])
        rm = ReferenceManager(hermes_path=str(tmp_path))
        report = rm.to_report()
        assert "Broken References" in report
        assert "ghost" in report

    def test_overlap_in_report(self, tmp_path):
        skills = tmp_path / "skills"
        _write_skill(skills, "web-scraper", description="Scrape websites for data")
        _write_skill(skills, "web-scrape", description="Scrape websites for data")
        rm = ReferenceManager(hermes_path=str(tmp_path))
        report = rm.to_report()
        assert "Overlapping Skills" in report or "No issues detected" in report


class TestKeywordOverlap:
    def test_identical_texts(self):
        assert ReferenceManager._keyword_overlap("hello world", "hello world") == 1.0

    def test_disjoint_texts(self):
        assert ReferenceManager._keyword_overlap("alpha bravo", "charlie delta") == 0.0

    def test_empty_text(self):
        assert ReferenceManager._keyword_overlap("", "hello") == 0.0
        assert ReferenceManager._keyword_overlap("hello", "") == 0.0
        assert ReferenceManager._keyword_overlap("", "") == 0.0

    def test_partial_overlap(self):
        score = ReferenceManager._keyword_overlap(
            "deploy kubernetes cluster", "deploy docker container"
        )
        assert 0.0 < score < 1.0
        assert score == pytest.approx(1 / 5, abs=0.01)  # "deploy" shared out of 5 total


class TestExtractKeywords:
    def test_basic(self):
        kw = _extract_keywords("Hello World! This is a TEST.")
        assert "hello" in kw
        assert "world" in kw
        assert "this" in kw
        assert "test" in kw
        # "is" and "a" are too short (3+ chars)
        assert "is" not in kw
        assert "a" not in kw

    def test_empty(self):
        assert _extract_keywords("") == set()


class TestEdgeCases:
    def test_nonexistent_path(self):
        rm = ReferenceManager(hermes_path="/nonexistent/path/xyz")
        assert rm.scan_references() == []
        assert rm.find_broken_references() == []

    def test_empty_skills_dir(self, tmp_path):
        (tmp_path / "skills").mkdir()
        rm = ReferenceManager(hermes_path=str(tmp_path))
        assert rm.scan_references() == []

    def test_non_skilldir_files_ignored(self, tmp_path):
        skills = tmp_path / "skills"
        skills.mkdir()
        (skills / "not-a-dir.md").write_text("text")
        rm = ReferenceManager(hermes_path=str(tmp_path))
        assert rm.scan_references() == []

    def test_missing_frontmatter(self, tmp_path):
        skills = tmp_path / "skills"
        d = skills / "bare"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("# Bare skill with no frontmatter")
        rm = ReferenceManager(hermes_path=str(tmp_path))
        refs = rm.scan_references()
        assert len(refs) == 1
        assert refs[0]["related_skills"] == []
