# پلن اجرایی — Skill Optimizer v2 (۱۰ فاز)
# هر فاز = یک ساب‌ایجنت + یک تست واقعی

> تاریخ: ۲۳ ژوئیه ۲۰۲۶
> وضعیت: در انتظار تایید کاربر

---

## فاز ۱: Session Grazer 🔍
**هدف:** خواندن سشن‌های گذشته و پیدا کردن اشتباهات واقعی

**زیرمجموعه‌ها:**
- اتصال به `session_search` برای جستجوی سشن‌ها
- پیدا کردن سشن‌هایی که skill جواب نداده
- استخراج (task_input, response, error) از هر سشن
- ذخیره نتایج به صورت ساختاریافته

**خروجی:** `evolution/core/session_grazer.py` — کلاس SessionGrazer

**تست واقعی:** اجرای SessionGrazer روی ۵ سشن اخیر → آیا اشتباهات پیدا میشن؟

---

## فاز ۲: Skill Gap Analyzer 🎯
**هدف:** تحلیل شکاف بین skill فعلی و عملکرد واقعی

**زیرمجموعه‌ها:**
- خواندن skill با `skill_view`
- مقایسه description با شکست‌های واقعی از Phase 1
- تشخیص "این skill کجا کم آورده"
- اولویت‌بندی مشکلات بر اساس تعداد تکرار

**خروجی:** `evolution/core/gap_analyzer.py` — کلاس SkillGapAnalyzer

**تست واقعی:** تحلیل `n8n-patterns` با داده‌های واقعی → آیا شکاف‌ها مشخص میشن؟

---

## فاز ۳: Patch Engine v1 ✏️
**هدف:** تولید متن patch برای SKILL.md بر اساس شکاف‌ها

**زیرمجموعه‌ها:**
- دریافت لیست شکاف‌ها از Phase 2
- تولید پیشنهاد patch با LLM
- فرمت diff ساده (old_text → new_text)
- بررسی ساختار YAML frontmatter

**خروجی:** `evolution/core/patch_engine.py` — کلاس PatchEngine

**تست واقعی:** تولید patch برای `n8n-patterns` → آیا patch معتبر و قابل اعماله؟

---

## فاز ۴: Benchmark Runner 📊
**هدف:** مقایسه A/B دو نسخه skill

**زیرمجموعه‌ها:**
- اجرای skill قبلی روی test cases
- اجرای skill جدید روی همون test cases
- مقایسه امتیازها (LLM-as-judge)
- محاسبه بهبود/افت

**خروجی:** `evolution/core/benchmark_runner.py` — کلاس BenchmarkRunner

**تست واقعی:** مقایسه `n8n-patterns` فعلی vs patched → آیا بهبود مشخصه؟

---

## فاز ۵: Version Manager 📦
**هدف:** نسخه‌گذاری git-مانند با rollback

**زیرمجموعه‌ها:**
- ذخیره snapshot قبل از patch
- ساختار `.versions/` برای هر skill
- metadata.json با امتیاز بنچمارک
- rollback به نسخه قبلی

**خروجی:** `evolution/core/version_manager.py` — کلاس VersionManager

**تست واقعی:** ذخیره ۳ نسخه از `n8n-patterns` + rollback به نسخه اول → آیا درست برمیگرده؟

---

## فاز ۶: Safety Net 🛡️
**هدف:** اعتبارسنجی + rollback خودکار + drift detection

**زیرمجموعه‌ها:**
- بررسی YAML frontmatter بعد از patch
- بررسی سایز (max 15KB)
- بررسی رشد (max 20%)
- drift detection: اگه امتیاز بیش از ۱۰٪ افت کرد → rollback

**خروجی:** `evolution/core/safety_net.py` — کلاس SafetyNet

**تست واقعی:** اعمال یک patch خراب → آیا rollback خودکار اجرا میشه؟

---

## فاز ۷: Reference Manager 🔗
**هدف:** مدیریت وابستگی‌های بین skill ها

**زیرمجموعه‌ها:**
- خواندن `related_skills` از frontmatter
- بررسی broken references
- تشخیص overlap بین مهارت‌ها
- پیشنهاد merge

**خروجی:** `evolution/core/ref_manager.py` — کلاس ReferenceManager

**تست واقعی:** بررسی ۱۰ skill → آیا broken reference پیدا میشه؟

---

## فاز ۸: MIPROv2 Integration ⚙️
**هدف:** اتصال DSPy optimizer به pipeline

**زیرمجموعه‌ها:**
- اتصال `evolve_skill.py` به Session Grazer
- استفاده از داده‌های واقعی به جای synthetic
- اجرای MIPROv2 با `--mipro-auto heavy`
- مقایسه نتایج synthetic vs واقعی

**خروجی:** آپدیت `evolution/skills/evolve_skill.py`

**تست واقعی:** اجرای MIPROv2 با داده‌های واقعی → آیا نتیجه بهتر از synthetic هست؟

---

## فاز ۹: Cron + Reporter 📱
**هدف:** اجرای شبانه خودکار + گزارش‌دهی

**زیرمجموعه‌ها:**
- ساخت cron job برای اجرای شبانه
- ارسال گزارش به Telegram
- ذخیره نتایج در mnemosyne
- health check

**خروجی:** `evolution/core/cron_runner.py` + cron job configuration

**تست واقعی:** اجرای دستی pipeline شبانه → آیا گزارش به Telegram ارسال میشه؟

---

## فاز ۱۰: Full Pipeline 🚀
**هدف:** ادغام کامل + تست end-to-end

**زیرمجموعه‌ها:**
- اتصال همه ۹ فاز به هم
- اجرای کامل: session → gap → patch → benchmark → version → safety
- تست روی ۳ skill متفاوت
- مقایسه نتایج

**خروجی:** `evolution/core/pipeline.py` — کلاس FullPipeline

**تست واقعی:** اجرای کامل pipeline روی `n8n-patterns` → آیا همه مراحل بدون خطا اجرا میشن؟

---

## جدول وابستگی‌ها

```
Phase 1 (Session Grazer)
    ↓
Phase 2 (Gap Analyzer) ← وابسته به Phase 1
    ↓
Phase 3 (Patch Engine) ← وابسته به Phase 2
    ↓
Phase 4 (Benchmark) ← وابسته به Phase 3
    ↓
Phase 5 (Version Manager) ← وابسته به Phase 4
    ↓
Phase 6 (Safety Net) ← وابسته به Phase 5
    ↓
Phase 7 (Reference Manager) ← مستقل (می‌تونه موازی باشه)
    ↓
Phase 8 (MIPROv2) ← وابسته به Phase 1-6
    ↓
Phase 9 (Cron + Reporter) ← وابسته به Phase 8
    ↓
Phase 10 (Full Pipeline) ← وابسته به Phase 1-9
```

## خلاصه فازها

| # | فاز | ماژول اصلی | تست |
|---|-----|-----------|-----|
| 1 | Session Grazer | `session_grazer.py` | خواندن ۵ سشن |
| 2 | Skill Gap Analyzer | `gap_analyzer.py` | تحلیل n8n-patterns |
| 3 | Patch Engine v1 | `patch_engine.py` | تولید patch معتبر |
| 4 | Benchmark Runner | `benchmark_runner.py` | مقایسه A/B |
| 5 | Version Manager | `version_manager.py` | ذخیره + rollback |
| 6 | Safety Net | `safety_net.py` | rollback خودکار |
| 7 | Reference Manager | `ref_manager.py` | پیدا کردن broken refs |
| 8 | MIPROv2 Integration | `evolve_skill.py` | اجرای واقعی |
| 9 | Cron + Reporter | `cron_runner.py` | ارسال گزارش |
| 10 | Full Pipeline | `pipeline.py` | end-to-end |
