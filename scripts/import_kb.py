# -*- coding: utf-8 -*-
"""
把扩充药物导入本地知识库（复用 server.import_drugs 的合并逻辑）。

用法：
  python scripts/import_kb.py ocr-work/final2.json --pharm ocr-work/pharm_items.json

说明：
  - 基础数据（final2.json）：zh/en/category/smiles/cid 等
  - 药理数据（pharm_items.json）：parent/pharmacophore/target/action/mt/sar/similar
  - 直接写回 data/drugs.json、data/drug_pharm.json、data/drug_names.csv
"""

import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
import server


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("final", help="清洗后的药物基础数据 JSON")
    ap.add_argument("--pharm", default="", help="药理条目 JSON")
    args = ap.parse_args()

    final = json.load(open(args.final, encoding="utf-8"))
    pharm_by_en = {}
    if args.pharm:
        for p in json.load(open(args.pharm, encoding="utf-8")):
            pharm_by_en[p["en"].lower()] = p

    items = []
    for d in final:
        item = {
            "zh": d["zh"],
            "en": d["en"],
            "category": d.get("category", ""),
            "cid": d.get("cid"),
            "smiles": d.get("smiles", ""),
            "formula": d.get("formula", ""),
            "mw": d.get("mw", ""),
            "iupac": d.get("iupac", ""),
            "inchikey": d.get("inchikey", ""),
        }
        p = pharm_by_en.get(d["en"].lower())
        if p:
            for k in ("parent", "pharmacophore", "target", "action", "mt", "sar", "similar"):
                if p.get(k):
                    item[k] = p[k]
        items.append(item)

    result = server.import_drugs(items)
    print("导入结果:", result)
    print("drugs.json 现有:", len(server.DRUGS))
    print("drug_pharm.json 现有:", len(server.DRUG_PHARM))


if __name__ == "__main__":
    main()
