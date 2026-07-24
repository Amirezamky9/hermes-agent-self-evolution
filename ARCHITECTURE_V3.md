# معماری بهینهساز Skills v3 — مبتنی بر تحقیق واقعی
# تاریخ: ۲۴ ژوئیه ۲۰۲۶
# مبنای تحقیق: GitHub (8 repos), Reddit (5 subs), HN, 5 framework comparison

---

## یافتههای کلیدی تحقیق

### ۱. الگوهای موفق از GitHub

| پروژه | ستاره | الگوی کلیدی |
|-------|-------|-------------|
| prompt-optimizer | 32.5K | Version history + smart favorites |
| DSPy | 12K | Modular Python + auto-optimize |
| PromptWizard | 3.9K | Self-evolving loop (LLM نقد خودش) |
| promptim | 897 | Task-file + evaluator functions |
| prompt-ops | 848 | YAML config + CLI workflow |
| Promptomatix | 971 | Zero-config + synthetic data |
| PromptAgent | 355 | MCTS search برای prompt variants |
| GPTSwarm | 1K | Graph-based optimization |

### ۲. الگوهای موفق از فریمورکها

| فریمورک | درس کلیدی |
|---------|-----------|
| Claude Code | SKILL.md + YAML frontmatter + triggers + multi-layer scope |
| Cursor | 4-mode activation (Always/Auto/Agent/Manual) + glob patterns |
| Aider | ساده‌ترین = بهترین (CONVENTIONS.md خالص) |
| LangChain | tools list explicit + LangSmith versioning + middleware |
| OpenAI | Model pin versioning + structured outputs |

### ۳. الگوهای موفق از Reddit/HN

| الگو | منبع |
|------|------|
| Single Unix tool (ساده‌تر = بهتر) | r/LocalLLaMA (1965 votes) |
| Cognitive load measurement | r/PromptEngineering |
| OpenEvolve (MAP-Elites) | r/MachineLearning |
| SPINE (خوانایی > کدنویسی) | r/artificial |
| Adaptive routing (56% cost reduction) | arxiv.org/abs/2504.17192 |

### ۴. دامهای شناختهشده

1. **بار شناختی بیش از حد** — >5 فعل + >2 ابزار = 45-72% شکست
2. **حذف stderr** — عامل کورکورانه تلاش میکنه
3. **داده باینری در context** — هدر دادن token
4. **نبود overflow mode** — فایل بزرگ context رو پر میکنه
5. **ابهام در پرامپت** — maybe/perhaps/might = حدس
6. **محدودیت متضاد** — زیاد = relaxation

---

## معماری v3 — ۵ لایه

```
┌─────────────────────────────────────────────────────────────┐
│                    Layer 5: Orchestrator                     │
│         Cron + Reporter + CLI + Telegram Delivery           │
├─────────────────────────────────────────────────────────────┤
│                    Layer 4: Safety Net                       │
│    Cognitive Load + Drift Detection + Auto-Rollback         │
├─────────────────────────────────────────────────────────────┤
│                    Layer 3: Optimizer                        │
│   Self-Evolving Loop + MIPROv2 + Benchmark A/B               │
├─────────────────────────────────────────────────────────────┤
│                    Layer 2: Analyzer                         │
│   Session Grazer + Gap Analyzer + Pattern Extractor          │
├─────────────────────────────────────────────────────────────┤
│                    Layer 1: Data Source                      │
│   SessionDB + Mnemosyne + Skill Files + Execution Traces     │
└─────────────────────────────────────────────────────────────┘
```

---

## لایه ۱: Data Source (وجود دارد)

**ورودی‌ها:**
- `session_search` → مکالمات واقعی + اشتباهات
- `mnemosyne_recall` → حافظه تجمعی
- `skill_view` → محتوای SKILL.md فعلی
- `session_stats.py` → آمار استفاده + امتیاز ارزش سشن

**خروجی:** structured data برای لایه ۲

**تغییر لازم:** اضافه کردن **execution trace extraction** — یعنی不只 متن مکالمه، بلکه tool call sequence و نتایج رو هم استخراج کنیم.

---

## لایه ۲: Analyzer (وجود دارد + ارتقا)

**ماژولهای موجود:**
- SessionGrazer ✅
- SkillGapAnalyzer ✅

**ماژول جدید: Pattern Extractor**
```
ورودی: failures از SessionGrazer
خروجی: الگوهای تکراری خطا
  - "skill X همیشه وقتی Y پرسیده میشه جواب نمیده"
  - "skill Z در زمینه W ضعیفه"
  - "skill A نیاز به refrence B داره"
```

**ماژول جدید: Cognitive Load Analyzer**
```
الگو از Reddit: 9 بُعد امتیازدهی
  1. تعداد تسک (تعداد افعال عملیاتی)
  2. عمق استدلال
  3. پیچیدگی ابزار
  4. تراکم محدودیت
  5. پیچیدگی خروجی
  6. پیچیدگی زمانی
  7. ابهام
  8. بار حالت مرزی
  9. فشار زمینه

خروجی: cognitive_load_score (0-100)
  < 30: سبک — مناسب
  30-60: متوسط — نیاز به توجه
  > 60: سنگین — احتمال شکست بالا
```

---

## لایه ۳: Optimizer (بزرگترین تغییر)

### ۳.۱: Self-Evolving Loop (الگوی PromptWizard)

```
while not converged:
    1. skill فعلی رو با test cases اجرا کن
    2. LLM نقد کنه: "کجا ضعیف بود؟ چرا؟"
    3. LLM patch پیشنهاد بده
    4. patch رو اعمال کن
    5. A/B benchmark (قدیم vs جدید)
    6. اگه بهتر بود → نگه دار
    7. اگه بدتر بود → rollback
    8. cognitive_load رو چک کن — نباید زیاد بشه
```

### ۳.۲: MIPROv2 Integration (موجود دارد)

```python
# حالتهای اجرا:
mode="session"    # از داده واقعی استفاده کن
mode="synthetic"  # از داده ساختگی
mode="hybrid"     # ترکیب: synthetic baseline + real failures
```

### ۳.۳: Structural Pattern Enforcer (جدید)

**بهینهساز باید این الگوها رو اضافه کنه:**

| الگو | چطوری | چرا |
|------|-------|-----|
| **Bash blocks** | تبدیل توضیح → اسکریپت | gstack: 96% موفق |
| **Error handling** | `2>/dev/null \|\| true` | gstack: 95% موفق |
| **Triggers** | الگوی متنی | Claude Code: ✅ |
| **When to invoke** | بخش صریح | Claude Code: ✅ |
| **Verification steps** | "چطوری مطمئن بشیم کار کرد" | Claude Code: ✅ |
| **Common Pitfalls** | "اشتباهات رایج" | Claude Code: ✅ |
| **Env vars** | `export KEY=value` | gstack: 97% |
| **Conditionals** | `if [ condition ]; then` | gstack: 89% |

### ۳.۴: Cognitive Load Penalty (جدید)

```
امتیاز نهایی = benchmark_score - cognitive_load_penalty

cognitive_load_penalty:
  if cognitive_load > 60: penalty = 0.15 (15%)
  if cognitive_load > 80: penalty = 0.30 (30%)
  if cognitive_load < 30: penalty = 0

یعنی: skill که بزرگ و پیچیده بشه، جریمه میکنه
```

---

## لایه ۴: Safety Net (وجود دارد + ارتقا)

**موجود:**
- Frontmatter validation ✅
- Size check ✅
- Growth limit ✅
- Drift detection ✅
- Auto-rollback ✅

**جدید:**
- **Cognitive load check** — اگه load > 80 بعد از patch → rollback
- **Structural completeness check** — آیا triggers, when-to-invoke, verification داره؟
- **Pattern regression check** — آیا bash blocks کمتر شدن؟
- **Error handling coverage** — آیا همه دستورات `2>/dev/null` دارن؟

---

## لایه ۵: Orchestrator (وجود دارد + ارتقا)

**موجود:**
- Pipeline ✅
- CronRunner ✅
- CLI ✅

**جدید:**
- **Telegram delivery** — گزارش شبانه با جزئیات
- **Mnemosyne storage** — ذخیره نتایج در حافظه
- **Health check** — آیا pipeline سالمه؟

---

## تغییرات کلیدی نسبت به v2

| بخش | v2 | v3 |
|-----|----|----|
| **داده** | synthetic فقط | session + synthetic hybrid |
| **ارزیابی** | LLM-as-judge | LLM-as-judge + cognitive load |
| **بهینهساز** | MIPROv2 | MIPROv2 + self-evolving loop |
| **ساختار** | فقط متن | ساختار gstack (bash, triggers, error handling) |
| **امتیازدهی** | فقط accuracy | accuracy + cognitive_load - structural_penalty |
| **حد سایز** | 15K ثابت | داینامیک: max(base_size × 1.5, 50K) |
| **Safety** | size + growth | + cognitive load + structural completeness |

---

## فازهای پیادهسازی v3

| فاز | کار | زمان |
|-----|-----|------|
| **A** | Cognitive Load Analyzer | 1 روز |
| **B** | Pattern Extractor | 1 روز |
| **C** | Self-Evolving Loop (PromptWizard pattern) | 2 روز |
| **D** | Structural Pattern Enforcer | 1 روز |
| **E** | Cognitive Load Penalty در scoring | 0.5 روز |
| **F** | Structural Completeness Check در SafetyNet | 0.5 روز |
| **G** | Telegram Delivery + Mnemosyne Storage | 1 روز |
| **H** | Hybrid Dataset (session + synthetic) | 1 روز |
| **I** | Integration + E2E Test | 1 روز |
| **J** | اجرای واقعی روی ۳ skill | 1 روز |

**مجموع: ~۱۰ روز**

---

## خلاصه در یک نگاه

```
الگوی موفق = gstack (executable) + Claude Code (structured) + DSPy (auto-optimize)

هدف:
  skill فعلی (متن خالص)
    → تحلیل (session + cognitive load)
    → بهینهسازی (self-evolving + structural enforcer)
    → اعتبارسنجی (benchmark + cognitive load + structural)
    → نسخهگذاری + rollback
    → گزارش
```
