# -*- coding: utf-8 -*-
"""
为知识库中缺少药理内容的药物拉取 PubChem PUG View 药理原文（英文），供翻译入库。

用法：
  python scripts/fetch_pubchem_pharm.py --out ocr-work/pubchem_raw.json
"""

import argparse
import json
import os
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
import server

_orig_http_json = server.http_json


def _fast_http_json(url, timeout=15, retries=1, limiter=server.PUB_LIMITER, headers=None):
    return _orig_http_json(url, timeout=timeout, retries=retries, limiter=limiter, headers=headers)


server.http_json = _fast_http_json


def fetch(cid):
    bucket = {}
    for heading in ("Mechanism of Action", "Metabolism", "Toxicity", "Pharmacology and Biochemistry"):
        url = (f"https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON"
               f"?heading={urllib.parse.quote(heading)}")
        try:
            data = server.http_json(url, timeout=15, retries=1)
            server._walk_sections(data.get("Record", {}).get("Section", []), bucket)
        except Exception:
            continue
    action = " ".join(bucket.get("Mechanism of Action", [])).strip()
    metab = " ".join(bucket.get("Metabolism", [])).strip()
    tox = " ".join(bucket.get("Toxicity Summary", []) or bucket.get("Human Toxicity Excerpts", [])).strip()
    if not action and not metab and not tox:
        return None
    return {
        "action_en": action[:1200],
        "mt_en": " ".join(x for x in (metab, tox) if x)[:1200],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    drugs = json.load(open(os.path.join(BASE, "data", "drugs.json"), encoding="utf-8"))
    pharm = json.load(open(os.path.join(BASE, "data", "drug_pharm.json"), encoding="utf-8"))
    need = []
    for d in drugs:
        zh = d["zh"]
        p = pharm.get(zh, {})
        if p.get("action") or p.get("mt"):
            continue
        if d.get("cid"):
            need.append(d)
    print("需要 PubChem 兜底的药物:", len(need))

    results = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch, d["cid"]): d for d in need}
        for i, fut in enumerate(as_completed(futs), 1):
            d = futs[fut]
            try:
                r = fut.result()
            except Exception:
                r = None
            if r:
                results[d["zh"]] = {"cid": d["cid"], "en": d.get("en", ""), **r}
            if i % 40 == 0:
                print("  进度 %d/%d，成功 %d" % (i, len(need), len(results)))

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print("拉取成功:", len(results), "输出:", args.out)


if __name__ == "__main__":
    main()
