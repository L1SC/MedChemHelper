# -*- coding: utf-8 -*-
"""
为扩充药物生成药理条目（drug_pharm.json 格式）。

策略：
  1. 优先使用人工精编表（--curated JSON：{zh 或 en: {parent,pharmacophore,target,action,mt,similar,sar}}）
  2. 其余药物从 OCR 上下文（enriched.json 的 context）提取关键句作为 action/mt

用法：
  python scripts/build_pharm.py enriched.json --curated curated.json --out pharm_items.json
"""

import argparse
import json
import re

SENT_SPLIT = re.compile(r"(?<=[。；;])")


def pick_sentences(context, keywords, limit=3):
    if not context:
        return []
    sents = [s.strip() for s in SENT_SPLIT.split(context) if len(s.strip()) > 6]
    out = []
    for s in sents:
        if any(k in s for k in keywords):
            out.append(s)
            if len(out) >= limit:
                break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("enriched")
    ap.add_argument("--curated", default="")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    enriched = json.load(open(args.enriched, encoding="utf-8"))
    curated = {}
    if args.curated:
        raw = json.load(open(args.curated, encoding="utf-8"))
        for k, v in raw.items():
            curated[k] = v
            if v.get("en"):
                curated[v["en"].lower()] = v

    items = []
    for d in enriched:
        zh = d["zh"]
        en = d["en"].lower()
        c = curated.get(zh) or curated.get(en) or {}
        ctx = d.get("context", "")
        item = {
            "zh": zh,
            "en": d["en"],
            "category": d.get("category", ""),
        }
        if c:
            for k in ("parent", "pharmacophore", "target", "action", "mt", "sar", "similar"):
                if c.get(k):
                    item[k] = c[k]
        if not item.get("action"):
            sents = pick_sentences(ctx, ["作用", "机制", "抑制", "激动", "阻断", "抗菌", "抗肿瘤", "用于", "治疗"])
            if sents:
                item["action"] = " ".join(sents[:2])
        if not item.get("mt"):
            sents = pick_sentences(ctx, ["不良", "毒性", "副作用", "代谢", "排泄", "半衰期", "慎用", "禁用", "过量"])
            if sents:
                item["mt"] = " ".join(sents[:2])
        if not item.get("target"):
            sents = pick_sentences(ctx, ["受体", "酶", "通道", "蛋白", "抑制"])
            if sents:
                item["target"] = sents[0]
        if ctx and (not item.get("action") or not item.get("mt")):
            item["context_ref"] = ctx[:400]
        items.append(item)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    n_curated = sum(1 for it in items if it.get("parent") or it.get("pharmacophore") or it.get("target"))
    n_ctx = sum(1 for it in items if not it.get("parent") and it.get("context_ref"))
    print("共 %d 条；含精编 %d 条；纯上下文摘录 %d 条" % (len(items), n_curated, n_ctx))


if __name__ == "__main__":
    main()
