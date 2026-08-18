# -*- coding: utf-8 -*-
"""
从教材 OCR 文本提取“中文名（英文名）”药物候选，供知识库导入。

用法：
  python scripts/extract_drugs.py ocr-work/yhx --out ocr-work/yhx-candidates.json

输出：
  [{zh, en, count, pages, in_db}] 按出现次数排序；in_db 表示是否已在知识库。
"""

import argparse
import glob
import json
import os
import re

ZH_RE = r"[\u4e00-\u9fa5A-Za-z0-9·\-]{2,16}"
EN_RE = r"[A-Za-z][A-Za-z0-9\- ]{1,40}"
PAT_ZH_EN = re.compile(rf"({ZH_RE})[（(]({EN_RE})[）)]")
PAT_EN_ZH = re.compile(rf"({EN_RE})[（(]({ZH_RE})[）)]")

STOP_ZH = {"药物化学", "药理学", "图", "表", "第", "章", "节", "页", "续表", "习题",
           "多选题", "单选题", "简答题", "名词解释", "结构式", "通用名", "商品名",
           "化学名", "作用", "用途", "不良反应", "代谢", "吸收", "分布", "排泄",
           "临床", "治疗", "剂量", "制剂", "片剂", "胶囊", "注射", "口服", "静脉"}
STOP_EN = {"table", "figure", "fig", "chapter", "page", "pages", "drug", "drugs",
           "acid", "base", "salt", "salt", "etc", "et al", "in", "of", "the", "and",
           "with", "from", "for", "are", "was", "were", "can", "may", "not", "all"}


def clean_zh(s):
    s = s.strip()
    # 去掉常见杂质
    if not s or len(s) < 2 or len(s) > 14:
        return ""
    if s[0].isdigit() and not re.match(r"^\d+[一二三四五六七八九十]?[、.]", s):
        return ""
    for w in STOP_ZH:
        if w in s and len(s) <= len(w) + 1:
            return ""
    if re.search(r"[0-9]{3,}", s):
        return ""
    return s


def clean_en(s):
    s = s.strip().lower()
    if not s or len(s) < 3 or len(s) > 40:
        return ""
    if s in STOP_EN:
        return ""
    if re.search(r"[0-9]{3,}", s):
        return ""
    # 排除以常见标点/句读结尾
    if re.search(r"[.,;:。，；：]$", s):
        s = s[:-1]
    return s


def extract(dir_path):
    hits = {}
    pages_of = {}
    files = sorted(glob.glob(os.path.join(dir_path, "page_*.txt")))
    for fp in files:
        pno = int(os.path.basename(fp)[5:9])
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        for m in PAT_ZH_EN.finditer(text):
            zh = clean_zh(m.group(1))
            en = clean_en(m.group(2))
            if zh and en:
                key = (zh, en)
                hits[key] = hits.get(key, 0) + 1
                pages_of.setdefault(key, []).append(pno)
        for m in PAT_EN_ZH.finditer(text):
            en = clean_en(m.group(1))
            zh = clean_zh(m.group(2))
            if zh and en:
                key = (zh, en)
                hits[key] = hits.get(key, 0) + 1
                pages_of.setdefault(key, []).append(pno)
    out = []
    for (zh, en), cnt in sorted(hits.items(), key=lambda x: -x[1]):
        pages = sorted(set(pages_of[(zh, en)]))
        out.append({"zh": zh, "en": en, "count": cnt, "pages": pages[:8]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", help="OCR 文本目录（page_*.txt）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--db", default=None, help="现有 drugs.json，用于标记 in_db")
    args = ap.parse_args()

    cands = extract(args.dir)
    in_db = set()
    if args.db and os.path.exists(args.db):
        db = json.load(open(args.db, encoding="utf-8"))
        for d in db:
            in_db.add(d.get("zh", ""))
            if d.get("en"):
                in_db.add(d["en"].lower())
    for c in cands:
        c["in_db"] = c["zh"] in in_db or c["en"].lower() in in_db
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(cands, f, ensure_ascii=False, indent=1)
    n_new = sum(1 for c in cands if not c["in_db"])
    print("共提取 %d 个候选，其中不在现有库 %d 个" % (len(cands), n_new))
    print("输出:", args.out)


if __name__ == "__main__":
    main()
