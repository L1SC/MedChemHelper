# -*- coding: utf-8 -*-
"""
从教材 OCR 全文为药物提取药理内容（含来源），补全 drug_pharm.json。

对每个药物：
  1. 在《药理学》《药物化学》OCR 文本中搜索中文名/英文名出现的页码
  2. 从出现页提取上下文句子，按关键词归类为 action / mt / target
  3. 记录来源：{book, chapter, page}

用法：
  python scripts/extract_pharm_from_ocr.py --out ocr-work/pharm_from_ocr.json
"""

import argparse
import glob
import json
import os
import re

CN_NUM = "一二三四五六七八九十百"
PAT_CHAPTER = re.compile(rf"第([{CN_NUM}]+)章\s*[\"“”·、:：]?\s*([\u4e00-\u9fa5A-Za-z0-9（）()\-·]{{2,24}})")

ACTION_KW = ("作用", "机制", "抑制", "激动", "阻断", "拮抗", "用于", "治疗", "抗菌",
             "抗肿瘤", "抗病毒", "杀菌", "抑菌", "促进", "减少", "增加", "激活", "降低")
MT_KW = ("不良", "毒性", "副作用", "代谢", "排泄", "半衰期", "慎用", "禁用", "过量",
         "中毒", "损伤", "反应", "注意", "禁忌", "监测")
TARGET_KW = ("受体", "酶", "通道", "蛋白", "结合", "抑制", "激动", "拮抗")


def build_page_chapter(ocr_dir, skip=8):
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


def chapter_for(mapping, pno):
    for p in range(pno, 0, -1):
        if p in mapping:
            return mapping[p]
    return ""


def load_texts(dirpath):
    out = {}
    for fp in glob.glob(os.path.join(dirpath, "page_*.txt")):
        pno = int(os.path.basename(fp)[5:9])
        out[pno] = open(fp, "r", encoding="utf-8", errors="ignore").read()
    return out


def clean_frag(s):
    """清洗 OCR 片段：去结构式碎片与噪声符号。"""
    s = re.sub(r"\s+", "", s)
    # 去掉括号包裹的化学碎片（如 (COOH)、(NH2)）
    s = re.sub(r"[（(][A-Za-z0-9+=\-·]{1,12}[)）]", "", s)
    # 去掉连续大写+数字的碎片
    s = re.sub(r"[A-Z]{2,}[0-9]*", "", s)
    s = re.sub(r"[\|>+*=×~`·]+", "", s)
    s = re.sub(r"[0-9]{2,}[\u4e00-\u9fa5]*", "", s)
    s = re.sub(r"[\u4e00-\u9fa5]{1,4}[A-Z][a-z]{1,3}\d*", "", s)
    return s.strip("。；;，,、 ")


def pick_window(text, name, kw, limit=2, window=220, span=70):
    """在药物名出现位置附近，按关键词定位内容片段。

    片段必须以药物名本身为锚点（避免截到同页其他药物的文本），
    并拒绝含章节标题/表格/剂量文本的碎片。
    """
    idxs = []
    pos = 0
    low = text.lower()
    nm = name.lower()
    while True:
        i = low.find(nm, pos)
        if i < 0:
            break
        idxs.append(i)
        pos = i + len(nm)
    if not idxs:
        return []
    out = []
    for i in idxs:
        seg = text[i: i + window]
        for k in kw:
            ki = seg.find(k)
            if ki >= 0:
                frag = seg[: max(0, ki + span)]
                frag = clean_frag(frag)
                # 片段必须包含药物名本身，且不含章节/表格/剂量等噪声
                if (len(frag) >= 12 and frag not in out
                        and name in frag
                        and not re.search(r"第[一二三四五六七八九十百\d]+章|表\s*\d|"
                                          r"\[?药理作用\]?|【体内过程】|制剂及用法|"
                                          r"每次\s*\d|mg/d|mg/(kg|次)", frag)):
                    out.append(frag)
                break
        if len(out) >= limit:
            break
    return out


def extract_for_drug(zh, en, texts_by_book, chapters_by_book):
    """返回 {action, mt, target, sources} 或 None。"""
    action, mt, target = [], [], []
    sources = []
    for book, texts in texts_by_book.items():
        chap_map = chapters_by_book[book]
        found_pages = []
        for pno, text in texts.items():
            if zh in text or (en and en.lower() in text.lower()):
                found_pages.append(pno)
        found_pages = found_pages[:6]
        for pno in found_pages:
            text = texts[pno]
            act = pick_window(text, zh or en, ACTION_KW, limit=1)
            m = pick_window(text, zh or en, MT_KW, limit=1)
            t = pick_window(text, zh or en, TARGET_KW, limit=1)
            if act:
                action.append(act[0])
            if m:
                mt.append(m[0])
            if t:
                # 靶点不应与药理/代谢文本重复（错配信号）
                if t[0] not in (action + mt):
                    target.append(t[0])
            if act or m or t:
                sources.append({
                    "book": book,
                    "chapter": chapter_for(chap_map, pno),
                    "page": pno,
                })
    if not action and not mt and not target:
        return None
    out = {}
    if action:
        out["action"] = "；".join(action[:2])
    if mt:
        out["mt"] = "；".join(mt[:2])
    if target:
        out["target"] = "；".join(target[:2])
    out["source"] = sources[:3]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--ocr-ylx", default=r"..\..\outputs\ocr-work\ylx")
    ap.add_argument("--ocr-yhx", default=r"..\..\outputs\ocr-work\yhx")
    args = ap.parse_args()

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    drugs = json.load(open(os.path.join(base, "data", "drugs.json"), encoding="utf-8"))
    pharm = json.load(open(os.path.join(base, "data", "drug_pharm.json"), encoding="utf-8"))

    ocr_ylx = os.path.join(base, args.ocr_ylx)
    ocr_yhx = os.path.join(base, args.ocr_yhx)
    texts = {"药理学": load_texts(ocr_ylx), "药物化学": load_texts(ocr_yhx)}
    chapters = {"药理学": build_page_chapter(ocr_ylx), "药物化学": build_page_chapter(ocr_yhx)}
    print("药理学页数:", len(texts["药理学"]), "药物化学页数:", len(texts["药物化学"]))

    results = {}
    n_missing = 0
    for d in drugs:
        zh = d["zh"]
        en = d.get("en", "")
        if zh in pharm and pharm[zh].get("action"):
            continue
        r = extract_for_drug(zh, en, texts, chapters)
        if r:
            results[zh] = r
        else:
            n_missing += 1
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    print("提取到药理的药物:", len(results), "仍未提取到:", n_missing)


if __name__ == "__main__":
    main()
