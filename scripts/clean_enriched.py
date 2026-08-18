# -*- coding: utf-8 -*-
"""
清洗 enrich 结果：过滤 OCR 噪音、合并出现频次、可选 PubChem 同义词二次校验。

用法：
  python scripts/clean_enriched.py enriched.json --candidates merged-candidates.json --out cleaned.json
"""

import argparse
import difflib
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
import server

_orig_http_json = server.http_json


def _fast_http_json(url, timeout=12, retries=1, limiter=server.PUB_LIMITER, headers=None):
    return _orig_http_json(url, timeout=timeout, retries=retries, limiter=limiter, headers=headers)


server.http_json = _fast_http_json

BAD_ZH_WORDS = ("结构修饰物", "转化酶", "环加氧酶", "环氧合酶", "受体激动药", "受体阻断药",
                "抑制剂", "激动药", "阻断药", "拮抗药", "类药物", "及抗", "和抗")
BAD_ZH_CHARS = re.compile(r"^[A-Za-z0-9 ]+$|^[A-Za-z]{1,2}$|\d{3,}")
BAD_EN = re.compile(r"^(ch\d|c2h\d|oac|meoh|etoh|ph|oh|co|cox|ace|atp|gdp|nad|hiv|rna|dna|d[abc])\b")


def is_garbage(item):
    zh = item.get("zh", "")
    en = item.get("en", "").lower()
    if not zh or len(zh) < 2 or len(zh) > 12:
        return True
    if BAD_ZH_CHARS.search(zh):
        return True
    if any(w in zh for w in BAD_ZH_WORDS):
        return True
    if len(en) < 3 or BAD_EN.match(en):
        return True
    if re.search(r"[0-9]{3,}", en):
        return True
    if re.match(r"^[A-Za-z][A-Za-z0-9]{0,2}$", en):
        return True
    return False


def syn_check(item):
    """用 PubChem 同义词校验/纠正中文名；返回 (item, score)。"""
    try:
        syns = server.pc_synonyms(item["cid"], limit=150)
    except Exception:
        syns = []
    zh_cands = [s.strip() for s in syns if re.search(r"[\u4e00-\u9fa5]{2,}", s)]
    if not zh_cands:
        return item, 0.9  # 无中文同义词：无法验证，保留（已通过规则过滤）
    best = max(zh_cands, key=lambda s: difflib.SequenceMatcher(None, item["zh"], s).ratio())
    score = difflib.SequenceMatcher(None, item["zh"], best).ratio()
    if score >= 0.72:
        item["zh"] = best
    return item, score


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("enriched")
    ap.add_argument("--candidates", default="")
    ap.add_argument("--out", required=True)
    ap.add_argument("--syn-check", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    data = json.load(open(args.enriched, encoding="utf-8"))
    count_map = {}
    if args.candidates:
        cands = json.load(open(args.candidates, encoding="utf-8"))
        for c in cands:
            count_map[c["en"].lower()] = max(count_map.get(c["en"].lower(), 0), c.get("count", 1))

    kept = []
    dropped = 0
    for d in data:
        if is_garbage(d):
            dropped += 1
            continue
        d["count"] = count_map.get(d["en"].lower(), 1)
        kept.append(d)

    if args.syn_check:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(syn_check, d): d for d in kept}
            out = []
            for fut in as_completed(futs):
                item, score = fut.result()
                if score >= 0.45:
                    out.append(item)
                else:
                    dropped += 1
        kept = out

    kept.sort(key=lambda x: -x.get("count", 1))
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(kept, f, ensure_ascii=False, indent=1)
    print("保留 %d 个，过滤 %d 个" % (len(kept), dropped))
    print("输出:", args.out)


if __name__ == "__main__":
    main()
