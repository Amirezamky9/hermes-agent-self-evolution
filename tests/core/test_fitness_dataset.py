"""Tests for fitness, dataset_builder, and CLI."""

import json
import tempfile
from pathlib import Path

import pytest

from evolution.core.fitness import FitnessScore, skill_fitness_metric, _parse_score
from evolution.core.dataset_builder import EvalDataset, EvalExample, GoldenDatasetLoader


# ── FitnessScore ────────────────────────────────────────────────────

class TestFitnessScore:
    def test_composite_default(self):
        s = FitnessScore(correctness=1.0, procedure_following=1.0, conciseness=1.0)
        assert s.composite == pytest.approx(1.0)

    def test_composite_zero_output(self):
        s = FitnessScore()
        assert s.composite == 0.0

    def test_composite_with_length_penalty(self):
        s = FitnessScore(correctness=1.0, procedure_following=1.0, conciseness=1.0, length_penalty=0.3)
        assert s.composite == pytest.approx(0.7)

    def test_composite_weighted(self):
        s = FitnessScore(correctness=1.0, procedure_following=0.0, conciseness=0.0)
        assert s.composite == pytest.approx(0.5)

    def test_composite_penalty_clamped(self):
        s = FitnessScore(correctness=0.0, length_penalty=1.0)
        assert s.composite >= 0.0


class TestParseScore:
    def test_float(self):
        assert _parse_score(0.75) == 0.75

    def test_int(self):
        assert _parse_score(1) == 1.0

    def test_string_number(self):
        assert _parse_score("0.5") == 0.5

    def test_invalid_string(self):
        assert _parse_score("not a number") == 0.5

    def test_clamped_above(self):
        assert _parse_score(2.0) == 1.0

    def test_clamped_below(self):
        assert _parse_score(-0.5) == 0.0

    def test_none(self):
        assert _parse_score(None) == 0.5


# ── EvalDataset ─────────────────────────────────────────────────────

class TestEvalDataset:
    def test_save_and_load(self, tmp_path):
        examples = [
            EvalExample(task_input="task1", expected_behavior="rubric1"),
            EvalExample(task_input="task2", expected_behavior="rubric2"),
        ]
        ds = EvalDataset(train=examples[:1], val=examples[1:], holdout=[])
        ds.save(tmp_path / "dataset")
        loaded = EvalDataset.load(tmp_path / "dataset")
        assert len(loaded.train) == 1
        assert len(loaded.val) == 1
        assert len(loaded.holdout) == 0

    def test_all_examples(self):
        ds = EvalDataset(
            train=[EvalExample(task_input="t1", expected_behavior="r1")],
            val=[EvalExample(task_input="t2", expected_behavior="r2")],
            holdout=[EvalExample(task_input="t3", expected_behavior="r3")],
        )
        assert len(ds.all_examples) == 3

    def test_to_dspy_examples(self):
        ds = EvalDataset(
            train=[EvalExample(task_input="t1", expected_behavior="r1")],
        )
        dspy_exs = ds.to_dspy_examples("train")
        assert len(dspy_exs) == 1
        assert dspy_exs[0].task_input == "t1"

    def test_save_creates_directory(self, tmp_path):
        ds = EvalDataset(train=[], val=[], holdout=[])
        ds.save(tmp_path / "new" / "dir")
        assert (tmp_path / "new" / "dir").exists()


class TestGoldenDatasetLoader:
    def test_load_split_files(self, tmp_path):
        # Write individual split files
        (tmp_path / "train.jsonl").write_text(
            json.dumps({"task_input": "t1", "expected_behavior": "r1"}) + "\n"
        )
        (tmp_path / "val.jsonl").write_text(
            json.dumps({"task_input": "t2", "expected_behavior": "r2"}) + "\n"
        )
        (tmp_path / "holdout.jsonl").write_text("")
        ds = GoldenDatasetLoader.load(tmp_path)
        assert len(ds.train) == 1
        assert len(ds.val) == 1

    def test_load_single_file(self, tmp_path):
        golden = tmp_path / "golden.jsonl"
        lines = [
            json.dumps({"task_input": f"t{i}", "expected_behavior": f"r{i}"})
            for i in range(6)
        ]
        golden.write_text("\n".join(lines) + "\n")
        ds = GoldenDatasetLoader.load(golden)
        total = len(ds.train) + len(ds.val) + len(ds.holdout)
        assert total == 6

    def test_load_nonexistent(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            GoldenDatasetLoader.load(tmp_path / "nonexistent")


# ── EvalExample ─────────────────────────────────────────────────────

class TestEvalExample:
    def test_to_dict(self):
        e = EvalExample(task_input="t", expected_behavior="r", difficulty="hard", category="debug")
        d = e.to_dict()
        assert d["task_input"] == "t"
        assert d["difficulty"] == "hard"

    def test_from_dict(self):
        d = {"task_input": "t", "expected_behavior": "r", "difficulty": "easy", "category": "test", "source": "manual"}
        e = EvalExample.from_dict(d)
        assert e.task_input == "t"
        assert e.source == "manual"
