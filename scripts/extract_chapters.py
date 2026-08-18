# -*- coding: utf-8 -*-
"""
从教材 OCR 全文提取章节结构：找出每个“第X章 标题”首次出现的页码。

用法：
  python scripts/extract_chapters.py ocr-work/ylx --out ocr-work/ylx-chapters.json

输出：
  [{no, title, page}]  按正文出现顺序；title 为章节标题主体。
"""

import argparse
import glob
import json
import os
import re

CN_NUM = "一二三四五六七八九十百"
PAT_CHAPTER = re.compile(rf"第([{CN_NUM}]+)章\s*[\"“”·、:：]?\s*([\u4e00-\u9fa5A-Za-z0-9（）()\-·]{2,24})")
PAT_CHAPTER_LOOSE = re.compile(rf"第([{CN_NUM}]+)章")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", help="OCR 文本目录")
    ap.add_argument("--out", required=True)
    ap.add_argument("--skip", type=int, default=0, help="跳过前 N 页（目录区）")
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.dir, "page_*.txt")),
                   key=lambda p: int(os.path.basename(p)[5:9]))
    chapters = []
    seen_no = set()
    for fp in files:
        pno = int(os.path.basename(fp)[5:9])
        if pno <= args.skip:
            continue
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        for m in PAT_CHAPTER.finditer(text):
            no = m.group(1)
            title = m.group(2).strip()
            if no in seen_no:
                continue
            # 排除目录页噪声：目录里的标题后常跟页码数字
            after = text[m.end():m.end() + 20]
            if re.search(r"\d{2,3}\s*$", after) or re.match(r"^\s*[“”\"\s]*\d{2,3}", after):
                continue
            seen_no.add(no)
            chapters.append({"no": no, "title": title, "page": pno})
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(chapters, f, ensure_ascii=False, indent=1)
    print("提取到 %d 章：" % len(chapters))
    for c in chapters:
        print("  %s 章 %s @p%d" % (c["no"], c["title"], c["page"]))


if __name__ == "__main__":
    main()
