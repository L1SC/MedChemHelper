# -*- coding: utf-8 -*-
"""
扩充知识库：OCR 候选药物 -> PubChem 验证 + 中文名纠正 + 章节类别 + 药理上下文。

用法：
  python scripts/enrich_drugs.py candidates.json --ocr ocr-work/ylx --out ocr-work/enriched.json

输出：
  [{zh, en, cid, smiles, formula, mw, iupac, inchikey, category,
    context, chapter, source_pages}]  已通过 PubChem 验证且不在现有库的药物。
"""

import argparse
import difflib
import glob
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
import server

_orig_http_json = server.http_json


def _fast_http_json(url, timeout=12, retries=1, limiter=server.PUB_LIMITER, headers=None):
    return _orig_http_json(url, timeout=timeout, retries=retries, limiter=limiter, headers=headers)


server.http_json = _fast_http_json

CN_NUM = "一二三四五六七八九十百"
PAT_CHAPTER = re.compile(rf"第([{CN_NUM}]+)章\s*[\"“”·、:：]?\s*([\u4e00-\u9fa5A-Za-z0-9（）()\-·]{{2,24}})")

SALT_ENDS = ("sodium", "hydrochloride", "calcium", "potassium", "magnesium", "zinc",
             "citrate", "bromide", "sulfate", "succinate", "fumarate", "maleate",
             "tartrate", "phosphate", "carbonate", "oxide", "mesylate", "besylate",
             "glucuronide", "lithium", "hemisulfate", "maleate", "pamoate")

OCR_CHAR_FIX = {"仓": "仑", "蔡": "萘", "享": "亨", "毗": "吡", "哩": "唑", "咤": "唑",
                "咄": "唑", "碌": "氯", "噢": "奥", "苹": "苯"}
OCR_PAIR_FIX = (("环两", "环丙"), ("两酸", "丙酸"), ("地西洋", "地西泮"),
                ("氯考素", "氯霉素"), ("和毛霍素", "氯霉素"), ("走素", "霉素"),
                ("阻消", "阻滞"), ("茶胺", "苯胺"))


def apply_ocr_fix(zh):
    for a, b in OCR_PAIR_FIX:
        zh = zh.replace(a, b)
    return "".join(OCR_CHAR_FIX.get(ch, ch) for ch in zh)


def strip_salt(en):
    en = en.strip().lower()
    parts = en.split()
    if len(parts) >= 2 and parts[-1] in SALT_ENDS:
        return " ".join(parts[:-1])
    return en


def build_page_chapter(ocr_dir, skip=20):
    """扫描正文页，每页取第一个“第X章 标题” -> {page: title}。"""
    mapping = {}
    files = sorted(glob.glob(os.path.join(ocr_dir, "page_*.txt")),
                   key=lambda p: int(os.path.basename(p)[5:9]))
    for fp in files:
        pno = int(os.path.basename(fp)[5:9])
        if pno <= skip:
            continue
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        m = PAT_CHAPTER.search(text)
        if m:
            mapping[pno] = m.group(2).strip()
    return mapping


def chapter_for_page(mapping, pno):
    """回溯最近章标题；若失败返回空。"""
    for p in range(pno, 0, -1):
        if p in mapping:
            return mapping[p]
    return ""


def vote_chapter(mapping, pages):
    """对候选出现的多个页面做章节投票，返回 (多数章, 票数)。"""
    votes = {}
    for p in pages:
        c = chapter_for_page(mapping, p)
        if c:
            votes[c] = votes.get(c, 0) + 1
    if not votes:
        return "", 0
    best = max(votes.items(), key=lambda kv: kv[1])
    return best[0], best[1]


def resolve(en):
    """英文名 -> (cid, props)。"""
    try:
        cids = server.pc_name_cids(en)
        if not cids:
            terms = server.pc_autocomplete(en, limit=5)
            for t in terms:
                cids = server.pc_name_cids(t)
                if cids:
                    break
        if not cids:
            return None, {}
        cid = int(cids[0])
        props = server.pc_props([cid]).get(cid) or {}
        return cid, props
    except Exception:
        return None, {}


def fix_zh(cid, ocr_zh):
    """用 PubChem 同义词纠正 OCR 中文名。返回 (zh, 是否修正)。"""
    zh0 = ocr_zh
    if zh0.startswith("盐酸") and len(zh0) > 2:
        zh0 = zh0[2:]
    zh0 = apply_ocr_fix(zh0)
    try:
        syns = server.pc_synonyms(cid, limit=120)
    except Exception:
        syns = []
    zh_cands = [s.strip() for s in syns if re.search(r"[\u4e00-\u9fa5]{2,}", s)]
    if not zh_cands:
        return zh0, zh0 != ocr_zh
    best = max(zh_cands, key=lambda s: difflib.SequenceMatcher(None, zh0, s).ratio())
    score = difflib.SequenceMatcher(None, zh0, best).ratio()
    if score >= 0.72:
        return best, best != ocr_zh
    return zh0, zh0 != ocr_zh


def extract_context(ocr_dir, pages):
    """取药物出现页的正文片段（去掉页眉页码行）。"""
    for p in pages:
        fp = os.path.join(ocr_dir, "page_%04d.txt" % p)
        if not os.path.exists(fp):
            continue
        try:
            text = open(fp, "r", encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            continue
        body = "\n".join(lines[1:])  # 去掉页眉
        if len(body) > 80:
            return body[:1600], p
    return "", 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates")
    ap.add_argument("--ocr", required=True)
    ap.add_argument("--ocr2", default="", help="第二本 OCR 目录（如药物化学）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--skip-syn-fix", action="store_true", help="跳过 PubChem 同义词中文纠正（仅用本地 OCR 纠错）")
    args = ap.parse_args()

    cands = json.load(open(args.candidates, encoding="utf-8"))
    # 过滤：不在库 + 英文名清洗去重
    seen_en = set()
    need = []
    for c in cands:
        if c.get("in_db"):
            continue
        en = strip_salt(c.get("en", ""))
        if not en or en in seen_en:
            continue
        if re.search(r"\d{3,}", en):
            continue
        seen_en.add(en)
        pages = c.get("pages_ylx") or c.get("pages_yhx") or []
        need.append({"zh": c["zh"], "en": en, "pages": pages, "pages_ylx": c.get("pages_ylx", []), "pages_yhx": c.get("pages_yhx", [])})
    print("待验证候选（去盐去重后）: %d" % len(need))

    page_chapter = build_page_chapter(args.ocr)
    print("正文章节映射页数: %d" % len(page_chapter))

    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(resolve, n["en"]): n for n in need}
        for i, fut in enumerate(as_completed(futs), 1):
            n = futs[fut]
            cid, props = fut.result()
            if not cid or not props.get("smiles"):
                continue
            if args.skip_syn_fix:
                zh0 = n["zh"]
                if zh0.startswith("盐酸") and len(zh0) > 2:
                    zh0 = zh0[2:]
                zh0 = apply_ocr_fix(zh0)
                zh, fixed = zh0, zh0 != n["zh"]
            else:
                zh, fixed = fix_zh(cid, n["zh"])
            vote_pages = n["pages_ylx"] or n["pages"]
            category, vote = vote_chapter(page_chapter, vote_pages) if vote_pages else ("", 0)
            category = category.rstrip("（(（:：·")
            p0 = vote_pages[0] if vote_pages else (n["pages"][0] if n["pages"] else 0)
            context, ctx_page = extract_context(args.ocr, n["pages_ylx"])
            if not context and args.ocr2:
                context, ctx_page = extract_context(args.ocr2, n["pages_yhx"])
            results.append({
                "zh": zh,
                "en": n["en"],
                "cid": cid,
                "smiles": props.get("smiles"),
                "formula": props.get("formula"),
                "mw": props.get("mw"),
                "iupac": props.get("iupac"),
                "inchikey": props.get("inchikey"),
                "category": category,
                "category_votes": vote,
                "chapter_page": p0,
                "context": context,
                "context_page": ctx_page,
                "zh_fixed": fixed,
                "ocr_zh": n["zh"],
            })
            if i % 50 == 0:
                print("  验证进度 %d/%d，已通过 %d" % (i, len(need), len(results)))

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print("完成：验证通过 %d 个，输出 %s" % (len(results), args.out))
    print("中文名被纠正示例：")
    shown = 0
    for r in results:
        if r["zh_fixed"] and shown < 20:
            print("  %s (%s) -> %s" % (r["ocr_zh"], r["en"], r["zh"]))
            shown += 1


if __name__ == "__main__":
    main()
