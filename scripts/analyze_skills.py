#!/usr/bin/env python3
"""Analyze skill structure — gstack and others."""
from pathlib import Path
import json

skills_dir = Path.home() / ".hermes" / "skills"
results = []

for p in sorted(skills_dir.rglob("SKILL.md")):
    rel = str(p.relative_to(skills_dir))
    content = p.read_text(errors="ignore")
    lines = content.split("\n")
    
    has_front = lines[0].strip() == "---" if lines else False
    has_name = any("name:" in l for l in lines[:10])
    has_desc = any("description:" in l for l in lines[:10])
    
    headings = len([l for l in lines if l.startswith("#")])
    bullets = len([l for l in lines if l.strip().startswith("- ")])
    code_b = content.count("```") // 2
    has_refs = any("references" in l.lower() or "related" in l.lower() for l in lines[:20])
    
    parent = p.parent
    has_scripts = (parent / "scripts").exists()
    has_refs_dir = (parent / "references").exists()
    has_templates = (parent / "templates").exists()
    linked = len(list(parent.glob("*"))) - 1  # files besides SKILL.md
    
    # Detect category
    parts = rel.split("/")
    category = parts[0] if len(parts) > 1 else "_root"
    
    results.append({
        "name": rel,
        "category": category,
        "chars": len(content),
        "kb": round(len(content) / 1024, 1),
        "lines": len(lines),
        "headings": headings,
        "bullets": bullets,
        "code_blocks": code_b,
        "frontmatter": has_front,
        "has_name": has_name,
        "has_desc": has_desc,
        "has_refs": has_refs,
        "scripts_dir": has_scripts,
        "refs_dir": has_refs_dir,
        "templates_dir": has_templates,
        "linked_files": linked,
    })

# Stats
total = len(results)
sizes = [r["chars"] for r in results]
avg = sum(sizes) / total
median = sorted(sizes)[total // 2]
max_r = max(results, key=lambda x: x["chars"])
min_r = min(results, key=lambda x: x["chars"])

print(f"\n📊 SKILL.md Structure Analysis ({total} skills)")
print(f"{'='*60}")
print(f"Avg size:  {avg/1024:.1f} KB ({avg:.0f} chars)")
print(f"Median:    {median/1024:.1f} KB ({median:.0f} chars)")
print(f"Max:       {max_r['kb']} KB — {max_r['name']}")
print(f"Min:       {min_r['kb']} KB — {min_r['name']}")
print()

# Frontmatter stats
fm_count = sum(1 for r in results if r["frontmatter"])
print(f"Frontmatter: {fm_count}/{total} ({fm_count/total*100:.0f}%)")
has_refs_count = sum(1 for r in results if r["has_refs"])
print(f"References:  {has_refs_count}/{total} ({has_refs_count/total*100:.0f}%)")
scr_count = sum(1 for r in results if r["scripts_dir"])
print(f"Scripts dir: {scr_count}/{total} ({scr_count/total*100:.0f}%)")
refd_count = sum(1 for r in results if r["refs_dir"])
print(f"References dir: {refd_count}/{total} ({refd_count/total*100:.0f}%)")
tmpl_count = sum(1 for r in results if r["templates_dir"])
print(f"Templates dir: {tmpl_count}/{total} ({tmpl_count/total*100:.0f}%)")
print()

# Top 15 biggest
print("Top 15 biggest skills:")
print(f"{'KB':>6} | {'Lines':>5} | {'Links':>5} | Name")
print("-" * 65)
for r in sorted(results, key=lambda x: -x["chars"])[:15]:
    links = []
    if r["scripts_dir"]: links.append("scr")
    if r["refs_dir"]: links.append("ref")
    if r["templates_dir"]: links.append("tpl")
    link_str = ",".join(links) if links else ""
    print(f"{r['kb']:>5.1f} | {r['lines']:>5} | {r['linked_files']:>5} | {r['name']:<40} {link_str}")

# Top 15 most structured (headings + bullets + code)
print()
print("Top 15 most structured (rich content):")
print(f"{'KB':>6} | {'#':>3} | {'-':>3} | {'```':>3} | Name")
print("-" * 65)
for r in sorted(results, key=lambda x: x["headings"] + x["bullets"] + x["code_blocks"], reverse=True)[:15]:
    print(f"{r['kb']:>5.1f} | {r['headings']:>3} | {r['bullets']:>3} | {r['code_blocks']:>3} | {r['name']:<40}")

# Category summary
print()
print("By category:")
cats = {}
for r in results:
    c = r["category"]
    if c not in cats:
        cats[c] = {"count": 0, "total_kb": 0, "total_links": 0}
    cats[c]["count"] += 1
    cats[c]["total_kb"] += r["kb"]
    cats[c]["total_links"] += r["linked_files"]

for c, v in sorted(cats.items(), key=lambda x: -x[1]["total_kb"]):
    avg_kb = v["total_kb"] / v["count"]
    print(f"  {c:<25} {v['count']:>3} skills, avg {avg_kb:.1f} KB, {v['total_links']}>linked files")
