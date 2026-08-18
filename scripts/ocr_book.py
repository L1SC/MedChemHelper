# -*- coding: utf-8 -*-
"""
教材 PDF OCR 管道：PyMuPDF 渲染页面 + Tesseract 中文识别，输出逐页文本。

用途：
  1. 把扫描版课本（无文字层）转成可检索的文本，供知识库导入
  2. 命令行示例：
     python scripts/ocr_book.py "D:\\xxx.pdf" --out ocr-work/xxx --start 1 --end 50 --dpi 200 --workers 4

依赖：
  pip install pymupdf
  Tesseract OCR（含 chi_sim.traineddata，可用 --tessdata 指定目录）
"""

import argparse
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor


def find_tesseract():
    cands = [
        os.environ.get("TESSERACT_CMD", ""),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for c in cands:
        if c and os.path.exists(c):
            return c
    return "tesseract"


def find_tessdata():
    env = os.environ.get("TESSDATA_PREFIX", "")
    if env and os.path.isdir(env):
        return env
    local = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Tesseract-OCR", "tessdata")
    if os.path.isdir(local):
        return local
    prog = os.path.join(os.environ.get("ProgramFiles", ""), "Tesseract-OCR", "tessdata")
    if os.path.isdir(prog):
        return prog
    return ""


def ocr_one(pdf_path, page_no, out_dir, dpi, tess_exe, tessdata):
    """渲染第 page_no（1 起）页并 OCR，写 page_XXXX.txt，返回 (page_no, 字符数)。"""
    import fitz  # 在子进程内导入，避免主进程额外开销

    os.makedirs(out_dir, exist_ok=True)
    txt_path = os.path.join(out_dir, "page_%04d.txt" % page_no)
    if os.path.exists(txt_path) and os.path.getsize(txt_path) > 20:
        return page_no, os.path.getsize(txt_path)

    doc = fitz.open(pdf_path)
    page = doc[page_no - 1]
    pix = page.get_pixmap(dpi=dpi)
    tmp = os.path.join(tempfile.gettempdir(), "ocr_%d_%d.png" % (os.getpid(), page_no))
    pix.save(tmp)
    doc.close()

    cmd = [tess_exe, tmp, txt_path.replace(".txt", ""), "--tessdata-dir", tessdata, "-l", "chi_sim", "--psm", "3"]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    try:
        os.remove(tmp)
    except OSError:
        pass
    size = os.path.getsize(txt_path) if os.path.exists(txt_path) else 0
    return page_no, size


def main():
    ap = argparse.ArgumentParser(description="教材 PDF OCR")
    ap.add_argument("pdf")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=0, help="0 表示到最后一页")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--tessdata", default=find_tessdata())
    args = ap.parse_args()

    import fitz
    doc = fitz.open(args.pdf)
    total = len(doc)
    doc.close()
    end = args.end or total
    end = min(end, total)

    tess = find_tesseract()
    if not os.path.exists(tess) and not tess.endswith((".exe", "")):
        print("未找到 tesseract，请安装或设置 TESSERACT_CMD", file=sys.stderr)
        return 1
    print("Tesseract:", tess)
    print("tessdata:", args.tessdata or "(默认)")
    print("页数范围: %d - %d / 共 %d 页" % (args.start, end, total))

    pages = list(range(args.start, end + 1))
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(ocr_one, args.pdf, p, args.out, args.dpi, tess, args.tessdata): p for p in pages}
        done = 0
        for fut in futs:
            try:
                pno, size = fut.result()
                done += 1
                if done % 20 == 0 or done == len(futs):
                    print("进度: %d/%d 页" % (done, len(futs)))
            except Exception as e:
                print("页面失败:", e, file=sys.stderr)
    print("完成，输出目录:", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
