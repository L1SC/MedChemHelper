# -*- coding: utf-8 -*-
"""把 functional_groups.json 中代表药物/药效药物的 SMILES 替换为权威来源
（优先 drugs.json，其次 PubChem 在线查询）。"""

import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import server

GROUPS_PATH = os.path.join(BASE, "data", "functional_groups.json")
DRUGS_PATH = os.path.join(BASE, "data", "drugs.json")


def main():
    groups = json.load(open(GROUPS_PATH, encoding="utf-8"))["groups"]
    drugs = json.load(open(DRUGS_PATH, encoding="utf-8"))
    by_zh = {d["zh"]: d for d in drugs}
    by_en = {d["en"].lower(): d for d in drugs}

    def lookup(zh, en):
        d = by_zh.get(zh) or by_en.get((en or "").lower())
        if d and d.get("smiles"):
            return d["smiles"], "drugs.json"
        if en:
            try:
                cids = server.pc_name_cids(en)
                if cids:
                    props = server.pc_props([cids[0]])
                    smi = props.get(cids[0], {}).get("smiles")
                    if smi:
                        return smi, "pubchem"
            except Exception:
                pass
        return None, None

    replaced = 0
    misses = []
    for g in groups:
        for d in (g.get("pharmacophore") or {}).get("drugs", []) + g.get("representatives", []):
            smi, src = lookup(d.get("name"), d.get("en"))
            if smi and smi != d.get("smiles"):
                d["smiles"] = smi
                replaced += 1
            elif not smi:
                misses.append((g["id"], d.get("name"), d.get("en")))

    with open(GROUPS_PATH, "w", encoding="utf-8") as f:
        json.dump({"groups": groups}, f, ensure_ascii=False, indent=2)

    print(f"replaced: {replaced}, missed: {len(misses)}")
    for m in misses:
        print("  MISS:", m)


if __name__ == "__main__":
    main()
