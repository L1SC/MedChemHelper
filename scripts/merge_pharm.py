# -*- coding: utf-8 -*-
"""
合并 OCR 提取的药理内容（带来源）到 drug_pharm.json。

用法：
  python scripts/merge_pharm.py ocr-work/pharm_from_ocr.json --curated ocr-work/curated.json
"""

import argparse
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ocr_pharm", help="extract_pharm_from_ocr.py 的输出")
    ap.add_argument("--curated", default="", help="人工精编 JSON（键为中文名）")
    args = ap.parse_args()

    path = os.path.join(BASE, "data", "drug_pharm.json")
    pharm = json.load(open(path, encoding="utf-8"))
    ocr = json.load(open(args.ocr_pharm, encoding="utf-8"))
    curated = {}
    if args.curated:
        curated = json.load(open(args.curated, encoding="utf-8"))

    n_fill = 0
    for zh, v in ocr.items():
        if zh in curated:
            continue  # 人工精编优先，不覆盖
        old = pharm.get(zh, {})
        merged = dict(old)
        for k in ("action", "mt", "target"):
            if not merged.get(k) and v.get(k):
                merged[k] = v[k]
        src = merged.get("source") or []
        if isinstance(src, list):
            for s in v.get("source", []):
                if s not in src:
                    src.append(s)
            merged["source"] = src[:5]
        if merged != old:
            pharm[zh] = merged
            n_fill += 1

    # 人工精编条目标注来源
    for zh, v in curated.items():
        if zh not in pharm:
            pharm[zh] = {}
        for k in ("parent", "pharmacophore", "target", "action", "mt", "sar", "similar"):
            if v.get(k):
                pharm[zh][k] = v[k]
        if not pharm[zh].get("source"):
            pharm[zh]["source"] = [{"book": "人工整理", "chapter": "药物化学/药理学知识精编", "page": 0}]

    with open(path, "w", encoding="utf-8") as f:
        json.dump(pharm, f, ensure_ascii=False, indent=1)
    print("填充/更新条目:", n_fill, "，总条目:", len(pharm))


if __name__ == "__main__":
    main()
