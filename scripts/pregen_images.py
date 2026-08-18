# -*- coding: utf-8 -*-
"""
预生成知识库全部结构图（WebP），存到 data/images_pre/，供打包内置。

用法：
  python scripts/pregen_images.py

输出：data/images_pre/{smiles_md5}.webp，与后端 render_smiles 的缓存键一致。
"""

import hashlib
import io
import json
import os
import sys

from rdkit import Chem
from rdkit.Chem import Draw
from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "data", "images_pre")
SIZE = 420


def key(smiles):
    return hashlib.md5(smiles.encode("utf-8")).hexdigest()


def render_webp(smiles):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None, None
    canon = Chem.MolToSmiles(mol)
    img = Draw.MolToImage(mol, size=(SIZE, SIZE), kekulize=True)
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=85)
    return canon, buf.getvalue()


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    drugs = json.load(open(os.path.join(BASE, "data", "drugs.json"), encoding="utf-8"))
    groups = json.load(open(os.path.join(BASE, "data", "functional_groups.json"), encoding="utf-8"))["groups"]
    items = [(d["zh"], d.get("smiles", "")) for d in drugs]
    items += [(g["zh"], g.get("smiles_example", "")) for g in groups]
    items = [(zh, s) for zh, s in items if s]

    ok = skipped = 0
    total = 0
    for zh, s in items:
        canon, data = render_webp(s)
        if canon is None:
            print("渲染失败:", zh)
            continue
        path = os.path.join(OUT_DIR, key(canon) + ".webp")
        if os.path.exists(path):
            skipped += 1
            total += os.path.getsize(path)
            continue
        with open(path, "wb") as f:
            f.write(data)
        total += len(data)
        ok += 1
    print(f"生成 {ok} 张，跳过已有 {skipped} 张，共 {len(items)} 张")
    print(f"总大小: {total/1024/1024:.2f} MB")
    print("输出目录:", OUT_DIR)


if __name__ == "__main__":
    sys.exit(main())
