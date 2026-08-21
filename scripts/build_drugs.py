# -*- coding: utf-8 -*-
"""
从 PubChem 批量构建药物库 data/drugs.json。

用法：
    .venv\\Scripts\\python scripts\\build_drugs.py

数据来源：data/drug_names.csv（中文名, 英文名, 类别）
支持断点续跑：已存在于 drugs.json 中的条目会跳过。
未解析成功的药名会记录到 data/drug_build_failures.txt。
"""

import csv
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import server  # 复用 server.py 中的 PubChem 封装与限速

# 加快 PubChem 响应：更短超时、更少重试（构建场景可容忍个别失败）
_orig_http_json = server.http_json


def _fast_http_json(url, timeout=20, retries=2, limiter=server.PUB_LIMITER, headers=None):
    return _orig_http_json(url, timeout=timeout, retries=retries, limiter=limiter, headers=headers)


server.http_json = _fast_http_json

CSV_PATH = os.path.join(BASE, "data", "drug_names.csv")
OUT_PATH = os.path.join(BASE, "data", "drugs.json")
FAIL_PATH = os.path.join(BASE, "data", "drug_build_failures.txt")

def load_csv():
    rows = []
    seen = set()
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            zh = (r.get("中文名") or "").strip()
            en = (r.get("英文名") or "").strip()
            cat = (r.get("类别") or "").strip()
            if not zh or not en:
                continue
            key = (zh, en)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"zh": zh, "en": en, "category": cat})
    return rows


def load_existing():
    if not os.path.exists(OUT_PATH):
        return {}, []
    data = json.load(open(OUT_PATH, encoding="utf-8"))
    by_zh = {d["zh"]: d for d in data}
    return by_zh, data


def resolve_cid(en):
    """英文通用名 -> PubChem CID（含自动补全回退）。"""
    try:
        cids = server.pc_name_cids(en)
        if cids:
            return cids[0]
    except Exception:
        pass
    terms = server.pc_autocomplete(en, limit=5)
    for t in terms:
        try:
            cids = server.pc_name_cids(t)
        except Exception:
            cids = []
        if cids:
            return cids[0]
    return None


def main():
    rows = load_csv()
    existing, out = load_existing()
    print(f"CSV 共 {len(rows)} 条，已存在 {len(existing)} 条")

    cid_by_zh = {}
    failed = []
    need = [r for r in rows if r["zh"] not in existing]
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {ex.submit(resolve_cid, r["en"]): r for r in need}
        for i, fut in enumerate(as_completed(futures), 1):
            r = futures[fut]
            try:
                cid = fut.result()
            except Exception:
                cid = None
            if cid:
                cid_by_zh[r["zh"]] = cid
            else:
                failed.append((r["zh"], r["en"]))
            if i % 100 == 0:
                print(f"  名称解析进度 {i}/{len(need)}，失败 {len(failed)}")

    print(f"名称解析完成：成功 {len(cid_by_zh)}，失败 {len(failed)}")

    # 批量获取属性（CAS 在工具“详情”里按需获取，这里不逐条拉取）
    cid_to_zh = {}
    for zh, cid in cid_by_zh.items():
        cid_to_zh.setdefault(cid, zh)
    all_cids = list(cid_to_zh.keys())
    props = {}
    for i in range(0, len(all_cids), server.PROPS_CHUNK):
        chunk = all_cids[i:i + server.PROPS_CHUNK]
        props.update(server.pc_props(chunk))
        print(f"  属性获取 {min(i + server.PROPS_CHUNK, len(all_cids))}/{len(all_cids)}")

    # 组装输出（保留已有条目并补充）
    seen_zh = set()
    result = []
    for r in rows:
        if r["zh"] in seen_zh:
            continue
        seen_zh.add(r["zh"])
        if r["zh"] in existing:
            entry = dict(existing[r["zh"]])
        else:
            entry = {"zh": r["zh"], "en": r["en"], "category": r["category"]}
        cid = cid_by_zh.get(r["zh"])
        if cid:
            p = props.get(cid, {})
            entry["cid"] = cid
            if p.get("smiles"):
                entry["smiles"] = p["smiles"]
            if p.get("formula"):
                entry["formula"] = p["formula"]
            if p.get("mw"):
                entry["mw"] = p["mw"]
            if p.get("iupac"):
                entry["iupac"] = p["iupac"]
            if p.get("inchikey"):
                entry["inchikey"] = p["inchikey"]
        result.append(entry)

    # CSV 是增量构建清单，不应删除已有但尚未列入 CSV 的人工/教材条目。
    for zh, entry in existing.items():
        if zh not in seen_zh:
            result.append(entry)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    with open(FAIL_PATH, "w", encoding="utf-8") as f:
        f.write("中文名\t英文名\n")
        for zh, en in failed:
            f.write(f"{zh}\t{en}\n")

    ok = sum(1 for d in result if d.get("cid"))
    print(f"drugs.json 写入完成：共 {len(result)} 条，含结构数据 {ok} 条，失败 {len(failed)} 条")
    if failed:
        print("失败名单见 data/drug_build_failures.txt：")
        for zh, en in failed[:30]:
            print("  ", zh, en)


if __name__ == "__main__":
    main()
