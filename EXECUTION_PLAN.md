# پلن اجرایی — MVP Auto Skill Optimizer
# hermes-agent-self-evolution

## هدف
MVP سیستم بهینه‌سازی خودکار skill های Hermes Agent با:
- Versioning (ردیابی نسخه‌ها)
- Rollback (بازگشت امن)
- Benchmark (ارزیابی کیفیت)
- Supervisor workflow (حلقه خودکار)
- SKILL.md ( discoverability توسط Hermes)
- CLI قابل استفاده
- تست‌های واقعی
- مستندات کامل

---

## فاز ۰: پاکسازی و آماده‌سازی (تسک ۱-۸)

| # | تسک | فایل | وضعیت |
|---|------|-------|-------|
| 1 | حذف `.egg-info/` از ریپو | `.gitignore` | ⬜ |
| 2 | حذف `evolution_versions.db` از ریپو | `.gitignore` | ⬜ |
| 3 | حذف `reports/phase1_validation_report.pdf` از ریپو | `.gitignore` | ⬜ |
| 4 | اضافه کردن `__pycache__/`, `.pytest_cache/`, `output/` به `.gitignore` | `.gitignore` | ⬜ |
| 5 | حذف فایل‌های stub خالی: `tools/__init__.py`, `prompts/__init__.py`, `code/__init__.py`, `monitor/__init__.py` | `evolution/` | ⬜ |
| 6 | ساختار پوشه‌ها رو تمیز کن — فقط پوشه‌هایی که کد دارن بمونن | `evolution/` | ⬜ |
| 7 | چک کن `__init__.py` ها خالی نباشن یا export داشته باشن | همه `__init__.py` | ⬜ |
| 8 | بررسی git status — مطمئن شو فقط فایل‌های لازم tracked هستن | `.gitignore` | ⬜ |

## فاز ۱: ساختار پروژه (تسک ۹-۱۸)

| # | تسک | فایل | وضعیت |
|---|------|-------|-------|
| 9 | ساخت `SKILL.md` اصلی برای پروژه | `SKILL.md` | ⬜ |
| 10 | ساخت `evolution/__main__.py` — entry point برای `python -m evolution` | `evolution/__main__.py` | ⬜ |
| 11 | اضافه کردن `scripts/run_optimize.sh` — اجرای ساده | `scripts/run_optimize.sh` | ⬜ |
| 12 | اضافه کردن `scripts/run_tests.sh` — اجرای تست‌ها | `scripts/run_tests.sh` | ⬜ |
| 13 | اضافه کردن `scripts/run_benchmark.sh` — اجرای benchmark | `scripts/run_benchmark.sh` | ⬜ |
| 14 | آپدیت `pyproject.toml` — entry points, dependencies, scripts | `pyproject.toml` | ⬜ |
| 15 | ساخت `AGENTS.md` یا `.hermes.md` برای پروژه | `AGENTS.md` | ⬜ |
| 16 | بررسی `setup.cfg` یا `setup.py` — آیا لازمه؟ | `pyproject.toml` | ⬜ |
| 17 | اضافه کردن `LICENSE` فایل | `LICENSE` | ⬜ |
| 18 | نصب و تست کردن `pip install -e ".[dev]"` | `pyproject.toml` | ⬜ |

## فاز ۲: Version Store — تست و تکمیل (تسک ۱۹-۲۸)

| # | تسک | فایل | وضعیت |
|---|------|-------|-------|
| 19 | تست `VersionStore.__init__` — ایجاد دیتابیس | `version_store.py` | ⬜ |
| 20 | تست `VersionStore.save` — ذخیره version | `version_store.py` | ⬜ |
| 21 | تست `VersionStore.get` — خواندن version | `version_store.py` | ⬜ |
| 22 | تست `VersionStore.get_latest` — آخرین نسخه | `version_store.py` | ⬜ |
| 23 | تست `VersionStore.list_versions` — لیست همه نسخه‌ها | `version_store.py` | ⬜ |
| 24 | تست `VersionStore.record_baseline` — ثبت baseline | `version_store.py` | ⬜ |
| 25 | تست `VersionStore.record_evolved` — ثبت evolved | `version_store.py` | ⬜ |
| 26 | تست `VersionStore.record_rollback` — ثبت rollback | `version_store.py` | ⬜ |
| 27 | تست edge case: version تکراری | `version_store.py` | ⬜ |
| 28 | تست edge case: skill بدون version | `version_store.py` | ⬜ |

## فاز ۳: Rollback Manager — تست و تکمیل (تسک ۲۹-۳۸)

| # | تسک | فایل | وضعیت |
|---|------|-------|-------|
| 29 | تست `RollbackManager.rollback_to_version` — بازگشت موفق | `rollback.py` | ⬜ |
| 30 | تست `RollbackManager.rollback_to_baseline` — بازگشت به اول | `rollback.py` | ⬜ |
| 31 | تست `RollbackManager.rollback_last` — بازگشت یک قدم | `rollback.py` | ⬜ |
| 32 | تست edge case: بازگشت به خودش | `rollback.py` | ⬜ |
| 33 | تست edge case: version وجود نداره | `rollback.py` | ⬜ |
| 34 | تست edge case: skill وجود نداره | `rollback.py` | ⬜ |
| 35 | تست `RollbackManager.diff_versions` — تفاوت دو نسخه | `rollback.py` | ⬜ |
| 36 | تست `RollbackManager.get_skill_text` — خواندن متن version | `rollback.py` | ⬜ |
| 37 | تست validate=False — bypass constraint check | `rollback.py` | ⬜ |
| 38 | تست rollback متوالی — چند بار پشت سر هم | `rollback.py` | ⬜ |

## فاز ۴: Constraints — تست و تکمیل (تسک ۳۹-۴۶)

| # | تسک | فایل | وضعیت |
|---|------|-------|-------|
| 39 | تست `_check_size` — skill زیر حد | `constraints.py` | ⬜ |
| 40 | تست `_check_size` — skill بالای حد | `constraints.py` | ⬜ |
| 41 | تست `_check_growth` — رشد مجاز | `constraints.py` | ⬜ |
| 42 | تست `_check_growth` — رشد بیش از حد | `constraints.py` | ⬜ |
| 43 | تست `_check_non_empty` — متن خالی | `constraints.py` | ⬜ |
| 44 | تست `_check_skill_structure` — فرمت درست | `constraints.py` | ⬜ |
| 45 | تست `_check_skill_structure` — فرمت نادرست | `constraints.py` | ⬜ |
| 46 | تست `validate_all` — ترکیب چند constraint | `constraints.py` | ⬜ |

## فاز ۵: Skill Module — تست و تکمیل (تسک ۴۷-۵۴)

| # | تسک | فایل | وضعیت |
|---|------|-------|-------|
| 47 | تست `load_skill` — فایل معتبر | `skill_module.py` | ⬜ |
| 48 |测试 `load_skill` — بدون frontmatter | `skill_module.py` | ⬜ |
| 49 |测试 `load_skill` — frontmatter خالی | `skill_module.py` | ⬜ |
| 50 |测试 `find_skill` — پیدا کردن skill | `skill_module.py` | ⬜ |
| 51 |测试 `find_skill` — skill وجود نداره | `skill_module.py` | ⬜ |
| 52 |测试 `find_skill` — fuzzy match | `skill_module.py` | ⬜ |
| 53 |测试 `SkillModule.forward` — اجرای مودول | `skill_module.py` | ⬜ |
| 54 |测试 `reassemble_skill` — بازسازی فایل | `skill_module.py` | ⬜ |

## فاز ۶: Fitness / LLM Judge — تست (تسک ۵۵-۶۰)

| # | تسک | فایل | وضعیت |
|---|------|-------|-------|
| 55 | تست `FitnessScore.composite` — محاسبه امتیاز | `fitness.py` | ⬜ |
| 56 | تست `FitnessScore` — length penalty | `fitness.py` | ⬜ |
| 57 | تست `skill_fitness_metric` — خروجی خالی | `fitness.py` | ⬜ |
| 58 | تست `skill_fitness_metric` — خروجی معتبر | `fitness.py` | ⬜ |
| 59 | تست `_parse_score` — عدد float | `fitness.py` | ⬜ |
| 60 | تست `_parse_score` — رشته نامعتبر | `fitness.py` | ⬜ |

## فاز ۷: Dataset Builder — تست (تسک ۶۱-۶۶)

| # | تسک | فایل | وضعیت |
|---|------|-------|-------|
| 61 | تست `EvalDataset.save` — ذخیره JSONL | `dataset_builder.py` | ⬜ |
| 62 | تست `EvalDataset.load` — خواندن JSONL | `dataset_builder.py` | ⬜ |
| 63 | تست `EvalDataset.to_dspy_examples` — تبدیل | `dataset_builder.py` | ⬜ |
| 64 | تست `GoldenDatasetLoader.load` — فایل تکی | `dataset_builder.py` | ⬜ |
| 65 | تست `GoldenDatasetLoader.load` — از قبل split شده | `dataset_builder.py` | ⬜ |
| 66 | تست `GoldenDatasetLoader.load` — فایل وجود نداره | `dataset_builder.py` | ⬜ |

## فاز ۸: CLI — تست (تسک ۶۷-۷۲)

| # | تسک | فایل | وضعیت |
|---|------|-------|-------|
| 67 | تست `hse --help` — نمایش دستورات | `cli.py` | ⬜ |
| 68 |测试 `hse versions --help` | `cli.py` | ⬜ |
| 69 |测试 `hse rollback --help` | `cli.py` | ⬜ |
| 70 |测试 `hse benchmark --help` | `cli.py` | ⬜ |
| 71 |测试 `hse evolve --help` | `cli.py` | ⬜ |
| 72 |测试 `hse supervisor --help` | `cli.py` | ⬜ |

## فاز ۹: Integration Test (تسک ۷۳-۷۶)

| # | تسک | فایل | وضعیت |
|---|------|-------|-------|
| 73 | تست کامل: `python -m evolution --help` | `__main__.py` | ⬜ |
| 74 | تست integration: VersionStore + RollbackManager | `test_versioning.py` | ⬜ |
| 75 |测试 integration: ConstraintValidator + VersionStore | `test_versioning.py` | ⬜ |
| 76 |测试 dry run: `hse evolve --skill test --dry-run` | `evolve_skill.py` | ⬜ |

## فاز ۱۰: مستندات و نهایی‌سازی (تسک ۷۷-۸۰)

| # | تسک | فایل | وضعیت |
|---|------|-------|-------|
| 77 | آپدیت README.md — Quick Start واقعی | `README.md` | ⬜ |
| 78 | مستندسازی CLI — نمونه استفاده | `README.md` | ⬜ |
| 79 | مستندسازی معماری — دیاگرام جریان داده | `README.md` | ⬜ |
| 80 | Push نهایی به fork + تایید | GitHub | ⬜ |

---

## خلاصه

| فاز | تعداد تسک | توضیح |
|-----|-----------|-------|
| ۰ | ۸ | پاکسازی |
| ۱ | ۱۰ | ساختار پروژه |
| ۲ | ۱۰ | Version Store |
| ۳ | ۱۰ | Rollback |
| ۴ | ۸ | Constraints |
| ۵ | ۸ | Skill Module |
| ۶ | ۶ | Fitness |
| ۷ | ۶ | Dataset Builder |
| ۸ | ۶ | CLI |
| ۹ | ۴ | Integration |
| ۱۰ | ۴ | مستندات |
| **مجموع** | **۸۰** | |

## ترتیب اجرا
فاز ۰ → ۱ → ۲ → ۳ → ۴ → ۵ → ۶ → ۷ → ۸ → ۹ → ۱۰

هر فاز بعد از تکمیل تست‌ها و تایید، commit می‌شه.
