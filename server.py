# -*- coding: utf-8 -*-
"""
化学结构速查助手 - 本地后端服务

功能：
  1. 通过 PubChem 检索化合物（名称 / 分子式 / SMILES / CAS，支持部分匹配）
  2. 调用 ChemToolsHub 将 SMILES 渲染成 2D 结构图并计算描述符
  3. RDKit（可选）本地识别官能团、渲染备用
  4. 相似化合物 / 子结构（官能团）搜索

仅使用 Python 标准库；RDKit 为可选增强（在 .venv 中提供）。
"""

import argparse
import base64
import hashlib
import io
import json
import mimetypes
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if getattr(sys, "frozen", False):
    # PyInstaller 打包模式：资源在 _MEIPASS，图片缓存放在可执行文件旁
    BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    RUN_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    RUN_DIR = BASE_DIR
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_DIR = os.path.join(BASE_DIR, "data")
IMAGE_DIR = os.path.join(RUN_DIR, "images")

PUB_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
AUTO_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/autocomplete/compound"
CTH_PAGE = "https://chemtoolshub.com/zh-hans/tools/molecular-descriptor-calculator/"
CTH_API = "https://chemtoolshub.com/zh-hans/tools/api/molecular-descriptor/"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "ChemHelper/1.0 (local study tool)")

PROP_NAMES = ("MolecularFormula,MolecularWeight,CanonicalSMILES,IUPACName,"
              "InChIKey,XLogP,TPSA,HBondDonorCount,HBondAcceptorCount,"
              "RotatableBondCount,ExactMass")

MAX_FORMULA = 400      # 分子式搜索最多展示的候选数
MAX_GENERAL = 40       # 其他搜索最多展示的候选数
PROPS_CHUNK = 50       # 批量属性一次取多少个 CID


# ---------------------------------------------------------------- 工具函数

def load_json(name):
    with open(os.path.join(DATA_DIR, name), "r", encoding="utf-8") as f:
        return json.load(f)


GROUPS = load_json("functional_groups.json")["groups"]
ZH_BASE = load_json("chinese_names.json")

# 药物库（由 scripts/build_drugs.py 从 PubChem 生成）
DRUGS = []
_drug_path = os.path.join(DATA_DIR, "drugs.json")
if os.path.exists(_drug_path):
    try:
        DRUGS = load_json("drugs.json")
    except Exception:
        DRUGS = []
DRUGS_BY_ZH = {d["zh"]: d for d in DRUGS}
DRUGS_BY_CID = {d.get("cid"): d for d in DRUGS if d.get("cid")}
CHINESE = {**ZH_BASE, **DRUGS_BY_ZH}   # 药物条目优先（含 CID/类别）

# 药物药理信息库（分类/母体/药效基团/靶点/药理/代谢毒理/相似药）
DRUG_PHARM = {}
_pp = os.path.join(DATA_DIR, "drug_pharm.json")
if os.path.exists(_pp):
    try:
        DRUG_PHARM = load_json("drug_pharm.json")
    except Exception:
        DRUG_PHARM = {}

# 同音/异形字规范化（噁=恶、䓬=卓、碸=砜、羥=羟、甙=苷、醯=酰）
HOMOPHONE_MAP = {"噁": "恶", "䓬": "卓", "碸": "砜", "羥": "羟", "甙": "苷", "醯": "酰"}


def norm_zh(s):
    return "".join(HOMOPHONE_MAP.get(ch, ch) for ch in s)

# 反向索引：英文名 / SMILES -> 中文名
ZH_BY_EN = {}
ZH_BY_SMILES = {}
CAT_BY_CID = {}


def _index_name(zh, info):
    en = info.get("en", "").lower()
    smi = info.get("smiles", "")
    if en:
        ZH_BY_EN.setdefault(en, zh)
    if smi:
        ZH_BY_SMILES.setdefault(smi, zh)
    cid = info.get("cid")
    if cid:
        CAT_BY_CID.setdefault(cid, info.get("category") or "")


for _zh, _info in ZH_BASE.items():
    _index_name(_zh, _info)
for _d in DRUGS:
    _index_name(_d["zh"], _d)

# 规范化中文索引（支持同音模糊搜索）
CHINESE_NORM = {norm_zh(k): k for k in CHINESE}


def pharm_for(cid, zh=None):
    """返回某药物的药理信息（按中文名或 CID）。"""
    if zh and zh in DRUG_PHARM:
        return DRUG_PHARM[zh]
    if cid:
        d = DRUGS_BY_CID.get(cid)
        if d and d.get("zh") in DRUG_PHARM:
            return DRUG_PHARM[d["zh"]]
    return {}


def category_for(cid, zh=None):
    if cid and cid in CAT_BY_CID:
        return CAT_BY_CID[cid]
    if zh:
        d = DRUGS_BY_ZH.get(zh)
        if d:
            return d.get("category") or ""
    return ""


def zh_name_for(en_name=None, smiles=None, iupac=None):
    for key in (en_name, iupac):
        if key:
            hit = ZH_BY_EN.get(str(key).strip().lower())
            if hit:
                return hit
    if smiles:
        hit = ZH_BY_SMILES.get(smiles)
        if hit:
            return hit
        canon = _canon(smiles)
        if canon:
            hit = ZH_BY_SMILES.get(canon)
            if hit:
                return hit
    return None


def _canon(smiles):
    if not HAVE_RDKIT:
        return None
    mol = rd_parse(smiles)
    if mol is None:
        return None
    try:
        return Chem.MolToSmiles(mol)
    except Exception:
        return None


class RateLimiter:
    """简单限速器：保证两次请求之间至少间隔 interval 秒。"""

    def __init__(self, interval):
        self.interval = interval
        self.lock = threading.Lock()
        self.next_t = 0.0

    def wait(self):
        with self.lock:
            now = time.time()
            if now < self.next_t:
                time.sleep(self.next_t - now)
                now = time.time()
            self.next_t = max(now, self.next_t) + self.interval


PUB_LIMITER = RateLimiter(0.28)   # PubChem 限速约 5 次/秒
CTH_LIMITER = RateLimiter(0.6)    # ChemToolsHub 请求间隔


class ApiError(Exception):
    pass


class NotFoundError(ApiError):
    pass


def http_json(url, timeout=30, retries=3, limiter=PUB_LIMITER, headers=None):
    """GET JSON；处理 429/网络错误重试；解析 PubChem Fault 信息。"""
    last_err = None
    for attempt in range(retries):
        limiter.wait()
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "application/json",
        })
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                raise ApiError("服务返回了无法解析的数据")
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                data = json.loads(e.read().decode("utf-8", "replace"))
                fault = data.get("Fault") or {}
                detail = fault.get("Message") or data.get("error") or ""
            except Exception:
                pass
            if e.code == 404:
                raise NotFoundError(detail or "未找到")
            if e.code == 429 and attempt < retries - 1:
                time.sleep(2 + attempt * 2)
                continue
            last_err = ApiError(detail or f"HTTP {e.code}")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = ApiError(f"网络错误: {e}")
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
                continue
    raise last_err or ApiError("请求失败")


def quote(s):
    return urllib.parse.quote(s, safe="")


def pubchem_url(path):
    return PUB_BASE + path


# ---------------------------------------------------------------- PubChem

def pc_autocomplete(q, limit=10):
    url = f"{AUTO_BASE}/{quote(q)}/json?limit={limit}"
    try:
        data = http_json(url, timeout=20)
        terms = data.get("dictionary_terms", {}).get("compound", [])
        seen, out = set(), []
        for t in terms:
            key = t.lower()
            if key not in seen:
                seen.add(key)
                out.append(t)
        return out
    except Exception:
        return []


def pc_name_cids(name):
    url = pubchem_url(f"/compound/name/{quote(name)}/cids/JSON")
    data = http_json(url, timeout=30)
    return list(data.get("IdentifierList", {}).get("CID", []))


def _poll_listkey(listkey, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        url = pubchem_url(f"/compound/listkey/{listkey}/cids/JSON")
        try:
            data = http_json(url, timeout=30)
        except NotFoundError:
            raise ApiError("PubChem 任务丢失，请重试")
        if "IdentifierList" in data:
            return list(data["IdentifierList"].get("CID", []))
        if "Waiting" in data:
            time.sleep(3)
            continue
        raise ApiError("PubChem 返回了意外结果")
    raise ApiError("PubChem 查询超时")


def _pc_search_cids(path, timeout=60):
    """通用搜索：处理 PubChem 异步 Waiting 任务。"""
    url = pubchem_url(path)
    data = http_json(url, timeout=30)
    if "IdentifierList" in data:
        return list(data["IdentifierList"].get("CID", []))
    if "Waiting" in data:
        return _poll_listkey(data["Waiting"]["ListKey"], timeout=timeout)
    if "Fault" in data:
        raise ApiError(data["Fault"].get("Message", "查询失败"))
    raise ApiError("PubChem 返回了意外结果")


def pc_formula_cids(formula):
    return _pc_search_cids(f"/compound/formula/{quote(formula)}/cids/JSON")


def pc_smiles_cids(smiles):
    try:
        return _pc_search_cids(f"/compound/smiles/{quote(smiles)}/cids/JSON")
    except NotFoundError:
        return []


def pc_fastsimilar_cids(cid, threshold=90, max_records=12):
    path = (f"/compound/fastsimilarity_2d/cid/{cid}/cids/JSON"
            f"?Threshold={threshold}&MaxRecords={max_records}")
    return _pc_search_cids(path, timeout=90)


def pc_fastsubstructure_cids(smiles, max_records=24):
    path = (f"/compound/fastsubstructure/smiles/{quote(smiles)}/cids/JSON"
            f"?MaxRecords={max_records}")
    return _pc_search_cids(path, timeout=90)


def pc_props(cids):
    """批量获取属性，返回 {cid: {...}}。"""
    result = {}
    for i in range(0, len(cids), PROPS_CHUNK):
        chunk = cids[i:i + PROPS_CHUNK]
        url = pubchem_url(f"/compound/cid/{','.join(map(str, chunk))}/property/{PROP_NAMES}/JSON")
        data = http_json(url, timeout=45)
        for p in data.get("PropertyTable", {}).get("Properties", []):
            cid = p.get("CID")
            if cid is None:
                continue
            result[cid] = {
                "cid": cid,
                "formula": p.get("MolecularFormula"),
                "mw": p.get("MolecularWeight"),
                "smiles": p.get("CanonicalSMILES") or p.get("ConnectivitySMILES"),
                "iupac": p.get("IUPACName"),
                "inchikey": p.get("InChIKey"),
                "xlogp": p.get("XLogP"),
                "tpsa": p.get("TPSA"),
                "hbd": p.get("HBondDonorCount"),
                "hba": p.get("HBondAcceptorCount"),
                "rotb": p.get("RotatableBondCount"),
                "exact_mass": p.get("ExactMass"),
            }
    return result


def pc_synonyms(cid, limit=40):
    url = pubchem_url(f"/compound/cid/{cid}/synonyms/JSON")
    try:
        data = http_json(url, timeout=30)
        info = data.get("InformationList", {}).get("Information", [])
        if info:
            return list(info[0].get("Synonym", []))[:limit]
    except Exception:
        pass
    return []


# ---------------------------------------------------------------- RDKit（可选）

try:
    from rdkit import Chem
    from rdkit.Chem import Descriptors, Draw, rdFMCS, rdMolDescriptors
    from rdkit import RDLogger
    RDLogger.DisableLog("rdApp.*")
    HAVE_RDKIT = True
except Exception:
    HAVE_RDKIT = False


def rd_parse(smiles):
    if not HAVE_RDKIT:
        return None
    try:
        return Chem.MolFromSmiles(smiles)
    except Exception:
        return None


def rd_descriptors(smiles):
    if not HAVE_RDKIT:
        return None
    mol = rd_parse(smiles)
    if mol is None:
        return None
    try:
        return {
            "mw": round(Descriptors.MolWt(mol), 2),
            "logp": round(Descriptors.MolLogP(mol), 2),
            "tpsa": round(Descriptors.TPSA(mol), 2),
            "rotb": rdMolDescriptors.CalcNumRotatableBonds(mol),
            "hbd": rdMolDescriptors.CalcNumHBD(mol),
            "hba": rdMolDescriptors.CalcNumHBA(mol),
            "rings": rdMolDescriptors.CalcNumRings(mol),
            "arom_rings": rdMolDescriptors.CalcNumAromaticRings(mol),
        }
    except Exception:
        return None


def rd_render_png(smiles, path):
    if not HAVE_RDKIT:
        return False
    mol = rd_parse(smiles)
    if mol is None:
        return False
    try:
        img = Draw.MolToImage(mol, size=(420, 420), kekulize=True)
        img.save(path, "PNG")
        return True
    except Exception:
        return False


# 预编译 SMARTS（每个基团可配置多个模式）
SMARTS_CACHE = []
for g in GROUPS:
    raw = g.get("smarts") or ""
    if isinstance(raw, str):
        raw = [raw]
    compiled = []
    if HAVE_RDKIT:
        for pat in raw:
            if not pat:
                continue
            try:
                q = Chem.MolFromSmarts(pat)
                if q is not None:
                    compiled.append(q)
            except Exception:
                pass
    SMARTS_CACHE.append(compiled)


def detect_groups(smiles):
    if not HAVE_RDKIT:
        return []
    mol = rd_parse(smiles)
    if mol is None:
        return []
    found = []
    for g, pats in zip(GROUPS, SMARTS_CACHE):
        matched = any(mol.HasSubstructMatch(p) for p in pats) if pats else False
        if matched:
            found.append({
                "id": g["id"],
                "zh": g["zh"],
                "en": g["en"],
                "symbol": g["symbol"],
            })
    return found


# ---------------------------------------------------------------- ChemToolsHub 渲染

class ChemToolsHub:
    def __init__(self):
        self.lock = threading.Lock()
        self.token = None
        self.cookie = None
        self.token_time = 0.0

    def _fetch_token(self):
        CTH_LIMITER.wait()
        req = urllib.request.Request(CTH_PAGE, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", "replace")
            set_cookies = resp.headers.get_all("Set-Cookie") or []
        m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', body)
        if not m:
            raise ApiError("无法从 ChemToolsHub 页面获取 CSRF 令牌")
        self.token = m.group(1)
        self.cookie = ""
        for c in set_cookies:
            if c.lower().startswith("csrftoken="):
                self.cookie = c.split(";", 1)[0].split("=", 1)[1]
                break
        self.token_time = time.time()

    def render(self, smiles):
        os.makedirs(IMAGE_DIR, exist_ok=True)
        key = hashlib.md5(smiles.encode("utf-8")).hexdigest()
        png_path = os.path.join(IMAGE_DIR, key + ".png")
        desc_path = os.path.join(IMAGE_DIR, key + ".json")
        if os.path.exists(png_path):
            desc = {}
            if os.path.exists(desc_path):
                try:
                    desc = json.load(open(desc_path, "r", encoding="utf-8"))
                except Exception:
                    desc = {}
            return png_path, desc

        with self.lock:
            CTH_LIMITER.wait()
            if not self.token or time.time() - self.token_time > 1800:
                self._fetch_token()
            payload = json.dumps({"substance": smiles}).encode("utf-8")
            headers = {
                "User-Agent": UA,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-CSRFToken": self.token,
                "Referer": CTH_PAGE,
            }
            if self.cookie:
                headers["Cookie"] = "csrftoken=" + self.cookie
            req = urllib.request.Request(CTH_API, data=payload, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=40) as resp:
                    data = json.loads(resp.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                if e.code in (400, 403):
                    # 令牌可能过期，重取一次
                    self._fetch_token()
                    headers["X-CSRFToken"] = self.token
                    if self.cookie:
                        headers["Cookie"] = "csrftoken=" + self.cookie
                    req = urllib.request.Request(CTH_API, data=payload, headers=headers)
                    with urllib.request.urlopen(req, timeout=40) as resp:
                        data = json.loads(resp.read().decode("utf-8", "replace"))
                else:
                    raise ApiError(f"ChemToolsHub 渲染失败 (HTTP {e.code})")
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                raise ApiError(f"ChemToolsHub 网络错误: {e}")

        if data.get("error"):
            raise ApiError(str(data["error"]))

        data_uri = data.get("structure_image", "")
        if not data_uri.startswith("data:image/png;base64,"):
            raise ApiError("ChemToolsHub 未返回结构图")
        raw = base64.b64decode(data_uri.split(",", 1)[1])
        with open(png_path, "wb") as f:
            f.write(raw)

        desc = {
            "mw": data.get("molecular_weight"),
            "logp": data.get("logp"),
            "tpsa": data.get("tpsa"),
            "rotb": data.get("rotatable_bonds"),
            "hbd": data.get("hbond_donors"),
            "hba": data.get("hbond_acceptors"),
            "rings": data.get("ring_count"),
            "arom_rings": data.get("aromatic_rings"),
        }
        try:
            with open(desc_path, "w", encoding="utf-8") as f:
                json.dump(desc, f, ensure_ascii=False)
        except Exception:
            pass
        return png_path, desc


CTH = ChemToolsHub()


def render_smiles(smiles, online=True):
    """渲染 SMILES -> (image_path, descriptors, source)。依次尝试：
    ChemToolsHub -> RDKit 本地 -> PubChem PNG URL。"""
    if HAVE_RDKIT:
        canon = rd_parse(smiles)
        if canon is not None:
            smiles = Chem.MolToSmiles(canon)
    if online:
        try:
            png_path, desc = CTH.render(smiles)
            return "/api/image/" + os.path.basename(png_path), desc, "chemtoolshub"
        except Exception:
            pass
    if HAVE_RDKIT:
        png_path = os.path.join(IMAGE_DIR, hashlib.md5(smiles.encode("utf-8")).hexdigest() + ".png")
        if rd_render_png(smiles, png_path):
            return "/api/image/" + os.path.basename(png_path), rd_descriptors(smiles) or {}, "rdkit"
    if online:
        # 最后的备用：PubChem 在线图片
        url = f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/{quote(smiles)}/PNG"
        return url, {}, "pubchem"
    raise ApiError("离线模式下无法渲染该结构（本地 RDKit 解析失败）")


def common_groups(query_smiles, cand_smiles, max_n=5):
    """返回两个分子共同含有的已知基团（如“都有苯环、都有 β-内酰胺环”）。"""
    if not HAVE_RDKIT or not query_smiles or not cand_smiles:
        return []
    mq = rd_parse(query_smiles)
    mc = rd_parse(cand_smiles)
    if mq is None or mc is None:
        return []
    out = []
    for g, pats in zip(GROUPS, SMARTS_CACHE):
        if not pats:
            continue
        if any(mq.HasSubstructMatch(p) for p in pats) and any(mc.HasSubstructMatch(p) for p in pats):
            out.append(g["zh"])
            if len(out) >= max_n:
                break
    return out


# ---------------------------------------------------------------- 检索逻辑

CAS_RE = re.compile(r"^\d{1,7}-\d{2}-\d$")
FORMULA_RE = re.compile(r"^[A-Z][a-z]?\d*([A-Z][a-z]?\d*)*$")


TWO_LETTER_ELEMENTS = (
    "He Li Be Ne Na Mg Al Si Cl Ar Ca Sc Ti Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr "
    "Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu "
    "Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th "
    "Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og"
).split()


def _looks_like_smiles(q):
    """强 SMILES 特征：符号或芳香原子+环数字。"""
    if not re.fullmatch(r"[A-Za-z0-9@+\-\[\]()#=%\\/.]+", q):
        return False
    if re.search(r"[=#()\[\]@\\%]", q):
        return True
    if re.search(r"[a-z]\d", q):
        return True
    return False


def detect_type(q):
    q = q.strip()
    if not q:
        return "name"
    if CAS_RE.match(q):
        return "cas"
    if _looks_like_smiles(q):
        return "smiles"
    if FORMULA_RE.match(q):
        has_two_letter = any(el in q for el in TWO_LETTER_ELEMENTS)
        if has_two_letter or re.search(r"\d", q):
            # 分子式与环式 SMILES 歧义时（如 C1CCCCC1），用 RDKit 判断
            if HAVE_RDKIT and rd_parse(q) is not None:
                return "smiles"
            return "formula"
        return "smiles"
    return "name"


def _enrich(cid, props, source):
    out = dict(props)
    out["source"] = source
    zh = zh_name_for(en_name=out.get("iupac"), smiles=out.get("smiles"))
    out["zh"] = zh
    out["category"] = category_for(cid, zh)
    ph = pharm_for(cid, zh)
    if ph:
        out["parent"] = ph.get("parent")
        out["pharmacophore"] = ph.get("pharmacophore")
        out["target"] = ph.get("target")
        out["action"] = ph.get("action")
        out["mt"] = ph.get("mt")
        out["sar"] = ph.get("sar")
        out["similar"] = ph.get("similar", [])
    out["groups"] = detect_groups(out.get("smiles") or "")
    return out


def _local_props(info):
    return {
        "cid": info.get("cid"),
        "formula": info.get("formula"),
        "mw": info.get("mw"),
        "smiles": info.get("smiles"),
        "iupac": info.get("iupac"),
        "inchikey": info.get("inchikey"),
    }


# 知识库导入锁：避免并发写盘
IMPORT_LOCK = threading.Lock()


def _write_json(name, obj):
    with open(os.path.join(DATA_DIR, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def import_drugs(items):
    """课本/资料导入通路：合并药物条目到本地知识库。

    items: [{zh, en, category, parent, pharmacophore, target, action,
             mt, similar, sar, smiles, cid, formula, mw, iupac, inchikey, ...}]
    缺基础属性时自动用英文名/中文名查 PubChem 补齐。
    返回 {"added": n, "updated": m, "skipped": k}。
    """
    if not isinstance(items, list):
        raise ApiError("drugs 必须是列表")
    added = updated = skipped = 0
    new_drugs = []
    with IMPORT_LOCK:
        for it in items:
            if not isinstance(it, dict):
                skipped += 1
                continue
            zh = str(it.get("zh") or "").strip()
            en = str(it.get("en") or "").strip()
            if not zh and not en:
                skipped += 1
                continue
            if not zh:
                # 无中文名：仅合并药理条目（用英文名做键），不进入主药物库
                ph = {k: it.get(k) for k in ("parent", "pharmacophore", "target", "action", "mt", "sar") if it.get(k)}
                if it.get("similar"):
                    ph["similar"] = it["similar"]
                if ph:
                    if en in DRUG_PHARM:
                        DRUG_PHARM[en].update(ph)
                    else:
                        DRUG_PHARM[en] = ph
                skipped += 1
                continue

            base = dict(it)
            base["zh"] = zh
            # 补齐基础属性（缺 SMILES/CID 时查 PubChem）
            if (not base.get("smiles") or not base.get("cid")) and (en or zh):
                try:
                    term = en or zh
                    cids = pc_name_cids(term)
                    if cids:
                        cid = int(cids[0])
                        props = pc_props([cid]).get(cid) or {}
                        base.setdefault("cid", cid)
                        for k in ("formula", "mw", "smiles", "iupac", "inchikey"):
                            if not base.get(k) and props.get(k):
                                base[k] = props[k]
                except Exception:
                    pass

            # 药理字段（非空才合并）
            ph = {k: base.get(k) for k in ("parent", "pharmacophore", "target", "action", "mt", "sar") if base.get(k)}
            if base.get("similar"):
                ph["similar"] = base["similar"]

            old = DRUGS_BY_ZH.get(zh)
            if old is not None:
                old.update({k: v for k, v in base.items() if v})
                updated += 1
            else:
                new_drugs.append(base)
                added += 1

            if ph:
                if zh in DRUG_PHARM:
                    DRUG_PHARM[zh].update(ph)
                else:
                    DRUG_PHARM[zh] = ph

        # 更新内存索引
        for d in new_drugs:
            DRUGS.append(d)
            DRUGS_BY_ZH[d["zh"]] = d
            if d.get("cid"):
                DRUGS_BY_CID[d["cid"]] = d
            CHINESE[d["zh"]] = d
            CHINESE_NORM[norm_zh(d["zh"])] = d["zh"]
            _index_name(d["zh"], d)

        if added or updated:
            _write_json("drugs.json", DRUGS)
            _write_json("drug_pharm.json", DRUG_PHARM)
            # 追加到 drug_names.csv（保留可重建来源），避免重复行
            csv_path = os.path.join(DATA_DIR, "drug_names.csv")
            existing = set()
            if os.path.exists(csv_path):
                with open(csv_path, "r", encoding="utf-8-sig") as f:
                    for row in f:
                        parts = row.strip().split(",")
                        if len(parts) >= 2:
                            existing.add(parts[0] + "\t" + parts[1])
            with open(csv_path, "a", encoding="utf-8-sig", newline="") as f:
                for d in new_drugs:
                    pair = (d.get("zh") or "") + "\t" + (d.get("en") or "")
                    if pair not in existing:
                        f.write("%s,%s,%s\n" % (d.get("zh", ""), d.get("en", ""), d.get("category", "")))
                        existing.add(pair)

    return {"added": added, "updated": updated, "skipped": skipped}


def group_match_ids(q):
    """查询是否命中官能团名称（支持同音异形字）。"""
    qn = norm_zh(q.strip()).lower()
    if not qn:
        return []
    hits = []
    for g in GROUPS:
        zh_n = norm_zh(g["zh"]).lower()
        en_n = norm_zh(g["en"]).lower()
        if qn in zh_n or zh_n in qn or qn in en_n or en_n in qn:
            hits.append({"id": g["id"], "zh": g["zh"], "symbol": g.get("symbol", "")})
        if len(hits) >= 5:
            break
    return hits


def _local_search(q, type_):
    """离线本地检索：仅用内置中文词典/药物库。"""
    qn = norm_zh(q.strip())
    matched = []
    if type_ in ("name", "cas"):
        keys = []
        if qn in CHINESE_NORM:
            keys = [CHINESE_NORM[qn]]
        elif re.search(r"[\u4e00-\u9fff]", q):
            keys = [CHINESE_NORM[k] for k in CHINESE_NORM if qn in k or k in qn][:8]
        for zh in keys:
            matched.append((zh, _local_props(CHINESE[zh]), "dict"))
    elif type_ == "formula":
        fq = re.sub(r"[^A-Za-z0-9]", "", q.upper())
        for zh, info in CHINESE.items():
            f = info.get("formula")
            if f and re.sub(r"[^A-Za-z0-9]", "", f.upper()) == fq:
                matched.append((zh, _local_props(info), "formula"))
    elif type_ == "smiles":
        mq = rd_parse(q)
        if mq is None:
            raise NotFoundError("离线模式：该 SMILES 本地无法解析，请检查写法。")
        cq = Chem.MolToSmiles(mq)
        for zh, info in CHINESE.items():
            smi = info.get("smiles")
            if smi:
                m = rd_parse(smi)
                if m is not None and Chem.MolToSmiles(m) == cq:
                    matched.append((zh, _local_props(info), "smiles"))
    if not matched:
        raise NotFoundError(
            "离线模式：本地词典中未找到匹配。请开启“允许联网搜索”，"
            "或使用词典内已有的中文药名 / 分子式 / SMILES。"
        )
    candidates = []
    for zh, props, src in matched[:MAX_GENERAL]:
        out = dict(props)
        out["source"] = src
        out["zh"] = zh
        out["category"] = category_for(props.get("cid"), zh)
        ph = pharm_for(props.get("cid"), zh)
        if ph:
            for k in ("parent", "pharmacophore", "target", "action", "mt", "sar"):
                out[k] = ph.get(k)
            out["similar"] = ph.get("similar", [])
        out["groups"] = detect_groups(props.get("smiles") or "")
        candidates.append(out)
    return {
        "query": q,
        "type": type_,
        "matched_zh": candidates[0]["zh"] if len(candidates) == 1 else None,
        "total": len(matched),
        "truncated": False,
        "offline": True,
        "groups_match": group_match_ids(q),
        "candidates": candidates,
    }


def do_search(q, type_="auto", online=True):
    q = q.strip()
    if not q:
        raise ApiError("请输入要查询的内容")
    if type_ == "auto":
        type_ = detect_type(q)

    if not online:
        return _local_search(q, type_)

    cid_sources = {}      # cid -> source
    matched_zh = None

    if type_ in ("name", "cas"):
        # 1) 中文词典（精确 + 子串，支持同音异形字）
        qn = norm_zh(q)
        zh_keys = []
        if qn in CHINESE_NORM:
            zh_keys = [CHINESE_NORM[qn]]
            matched_zh = zh_keys[0]
        elif re.search(r"[\u4e00-\u9fff]", q):
            zh_keys = [CHINESE_NORM[k] for k in CHINESE_NORM if qn in k or k in qn][:6]
            if len(zh_keys) == 1:
                matched_zh = zh_keys[0]
        for zh in zh_keys:
            en = CHINESE[zh]["en"]
            try:
                for cid in pc_name_cids(en):
                    cid_sources.setdefault(cid, "dict")
            except Exception:
                continue

        # 2) PubChem 自动补全（英文部分匹配）
        if not re.search(r"[\u4e00-\u9fff]", q):
            terms = pc_autocomplete(q, limit=12)
            if terms:
                for term in terms[:10]:
                    try:
                        for cid in pc_name_cids(term):
                            cid_sources.setdefault(cid, "autocomplete")
                    except Exception:
                        continue
            # 3) 精确名称
            try:
                for cid in pc_name_cids(q):
                    cid_sources.setdefault(cid, "name")
            except Exception:
                pass

    elif type_ == "formula":
        try:
            cids = pc_formula_cids(q)
        except ApiError as e:
            raise ApiError(f"分子式查询失败：{e}")
        for cid in cids:
            cid_sources.setdefault(cid, "formula")

    elif type_ == "smiles":
        canon = q
        parsed = None
        if HAVE_RDKIT:
            parsed = rd_parse(q)
            if parsed is not None:
                canon = Chem.MolToSmiles(parsed)
        if parsed is not None:
            for cid in pc_smiles_cids(canon):
                cid_sources.setdefault(cid, "smiles")
        # 解析失败或精确结构找不到时，回退为名称搜索
        if not cid_sources:
            try:
                for cid in pc_name_cids(q):
                    cid_sources.setdefault(cid, "name")
            except Exception:
                pass
        if not cid_sources:
            if parsed is None:
                raise NotFoundError(
                    "输入既不像有效的 SMILES，也没有匹配到化合物名称。"
                    "请检查写法，或选择“名称”类型后再试。"
                )
            raise NotFoundError("该结构在 PubChem 中未找到精确匹配。")

    if not cid_sources:
        raise NotFoundError(
            "没有找到匹配的化合物。中文名请用常见名称（如“乙醇”）；"
            "英文支持部分匹配；也可以试试分子式（如 C2H6O）、SMILES（如 CCO）或 CAS 号。"
        )

    order = [c for c, s in cid_sources.items()][: (MAX_FORMULA if type_ == "formula" else MAX_GENERAL)]
    total = len(cid_sources)
    truncated = total > len(order)
    props = pc_props(order)
    candidates = [_enrich(cid, props.get(cid, {"cid": cid}), cid_sources.get(cid, "search"))
                  for cid in order if cid in props]
    if matched_zh:
        for c in candidates:
            if not c.get("zh"):
                c["zh"] = matched_zh
    # 有中文名/来源优先排序：autocomplete/name/dict 在前
    rank = {"dict": 0, "name": 1, "autocomplete": 2, "cas": 1, "smiles": 3, "formula": 4}
    candidates.sort(key=lambda c: (rank.get(c.get("source"), 5), c.get("cid") or 0))
    return {
        "query": q,
        "type": type_,
        "matched_zh": matched_zh,
        "total": total,
        "truncated": truncated,
        "offline": False,
        "groups_match": group_match_ids(q),
        "candidates": candidates,
    }


def compound_detail(cid):
    props = pc_props([cid]).get(cid)
    if not props:
        raise NotFoundError("未找到该化合物")
    out = dict(props)
    syns = pc_synonyms(cid, limit=60)
    cas = ""
    for s in syns:
        if CAS_RE.match(s.strip()):
            cas = s.strip()
            break
    names = [s for s in syns if not CAS_RE.match(s.strip())][:20]
    out["cas"] = cas
    out["names"] = names
    out["zh"] = zh_name_for(en_name=out.get("iupac"), smiles=out.get("smiles"))
    out["category"] = category_for(cid, out.get("zh"))
    ph = pharm_for(cid, out.get("zh"))
    if ph:
        for k in ("parent", "pharmacophore", "target", "action", "mt", "sar"):
            out[k] = ph.get(k)
        out["similar"] = ph.get("similar", [])
    out["groups"] = detect_groups(out.get("smiles") or "")
    out["source"] = "detail"
    return out


# ---------------------------------------------------------------- 联网检测 / PubChem 药理兜底

NETWORK_CACHE = {"t": 0.0, "result": None}


def _quick_ok(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            return resp.status < 500
    except Exception:
        return False


def check_network():
    now = time.time()
    if NETWORK_CACHE["result"] and now - NETWORK_CACHE["t"] < 30:
        return NETWORK_CACHE["result"]
    pub = _quick_ok("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/2244/property/MolecularFormula/JSON")
    cth = _quick_ok(CTH_PAGE)
    res = {"pubchem": pub, "chemtoolshub": cth, "online": pub or cth}
    NETWORK_CACHE.update({"t": now, "result": res})
    return res


def _walk_sections(sections, bucket):
    for sec in sections or []:
        heading = sec.get("TOCHeading", "")
        for inf in sec.get("Information") or []:
            val = inf.get("Value") or {}
            texts = []
            for sm in val.get("StringWithMarkup") or []:
                if sm.get("String"):
                    texts.append(sm["String"])
            if val.get("StringValue"):
                texts.append(val["StringValue"])
            if texts:
                bucket.setdefault(heading, []).extend(t for t in texts if t.strip())
        if sec.get("Section"):
            _walk_sections(sec["Section"], bucket)


def _pugview_pharm(cid):
    """从 PubChem PUG View 提取药理/代谢/毒性文字（兜底，缓存到磁盘）。"""
    cache = os.path.join(IMAGE_DIR, f"pugview_{cid}.json")
    if os.path.exists(cache):
        try:
            return json.load(open(cache, "r", encoding="utf-8"))
        except Exception:
            pass
    bucket = {}
    for heading in ("Mechanism of Action", "Metabolism", "Toxicity"):
        url = (f"https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON"
               f"?heading={urllib.parse.quote(heading)}")
        try:
            data = http_json(url, timeout=25, retries=1)
            _walk_sections(data.get("Record", {}).get("Section", []), bucket)
        except Exception:
            continue
    mech = " ".join(bucket.get("Mechanism of Action", [])).strip()
    metab = " ".join(bucket.get("Metabolism", [])).strip()
    tox = " ".join(bucket.get("Toxicity Summary", []) or bucket.get("Human Toxicity Excerpts", [])).strip()
    result = {
        "source": "pubchem",
        "action": mech[:800] or "",
        "mt": "；".join(x for x in (metab, tox) if x)[:800] or "",
    }
    try:
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
    except Exception:
        pass
    return result


def pharm_detail(cid, zh=None):
    ph = pharm_for(cid, zh)
    if ph:
        return {"source": "curated", **ph}
    return _pugview_pharm(cid)


# ---------------------------------------------------------------- HTTP 服务

class Handler(BaseHTTPRequestHandler):
    server_version = "MedChemHelper/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type=None, cache=True):
        if not os.path.isfile(path):
            self._send_json({"error": "文件不存在"}, 404)
            return
        with open(path, "rb") as f:
            body = f.read()
        ct = content_type or mimetypes.guess_type(path)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        if cache:
            self.send_header("Cache-Control", "public, max-age=86400")
        else:
            self.send_header("Cache-Control", "no-cache, max-age=0, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            raise ApiError("请求体不是有效的 JSON")

    def do_GET(self):
        try:
            path = urllib.parse.urlparse(self.path).path
            if path in ("/", "/index.html"):
                self._send_file(os.path.join(STATIC_DIR, "index.html"), "text/html; charset=utf-8", cache=False)
            elif path == "/api/groups":
                self._send_json({"groups": GROUPS})
            elif path == "/api/dict":
                self._send_json(CHINESE)
            elif path == "/api/network":
                self._send_json(check_network())
            elif path.startswith("/api/image/"):
                name = os.path.basename(path)
                self._send_file(os.path.join(IMAGE_DIR, name), "image/png")
            elif path.startswith("/static/"):
                name = os.path.basename(path)
                self._send_file(os.path.join(STATIC_DIR, name), cache=(not name.endswith((".js", ".css"))))
            elif path == "/api/health":
                self._send_json({"ok": True, "rdkit": HAVE_RDKIT})
            else:
                self._send_json({"error": "接口不存在"}, 404)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def do_POST(self):
        try:
            body = self._read_json()
            path = urllib.parse.urlparse(self.path).path
            if path == "/api/search":
                result = do_search(body.get("q", ""), body.get("type", "auto"),
                                   online=bool(body.get("online", True)))
                self._send_json(result)
            elif path == "/api/import":
                result = import_drugs(body.get("drugs") or [])
                self._send_json(result)
            elif path == "/api/render":
                smiles = body.get("smiles", "").strip()
                if not smiles:
                    raise ApiError("缺少 SMILES")
                image, desc, source = render_smiles(smiles, online=bool(body.get("online", True)))
                self._send_json({"image": image, "descriptors": desc, "source": source})
            elif path == "/api/compound":
                cid = int(body.get("cid", 0))
                self._send_json(compound_detail(cid))
            elif path == "/api/pharm":
                cid = int(body.get("cid", 0))
                zh = body.get("zh") or ""
                self._send_json(pharm_detail(cid, zh))
            elif path == "/api/similar":
                if not body.get("online", True):
                    raise ApiError("相似化合物需要联网搜索，请打开“允许联网搜索”开关。")
                cid = int(body.get("cid", 0))
                threshold = int(body.get("threshold", 90))
                max_rec = min(int(body.get("max", 12)), 20)
                cids = pc_fastsimilar_cids(cid, threshold, max_rec)
                cids = [c for c in cids if c != cid]
                props = pc_props(cids)
                q_smiles = (DRUGS_BY_CID.get(cid) or {}).get("smiles") or ""
                if not q_smiles:
                    q_smiles = (pc_props([cid]).get(cid) or {}).get("smiles") or ""
                candidates = []
                for c in cids:
                    if c not in props:
                        continue
                    cand = _enrich(c, props.get(c, {"cid": c}), "similar")
                    cand["common"] = common_groups(q_smiles, cand.get("smiles") or "")
                    candidates.append(cand)
                self._send_json({"candidates": candidates})
            elif path == "/api/substructure":
                if not body.get("online", True):
                    raise ApiError("官能团子结构搜索需要联网，请打开“允许联网搜索”开关。")
                smiles = body.get("smiles", "").strip()
                max_rec = min(int(body.get("max", 24)), 50)
                cids = pc_fastsubstructure_cids(smiles, max_rec)
                props = pc_props(cids)
                candidates = [_enrich(c, props.get(c, {"cid": c}), "substructure") for c in cids if c in props]
                self._send_json({"candidates": candidates})
            else:
                self._send_json({"error": "接口不存在"}, 404)
        except NotFoundError as e:
            self._send_json({"error": str(e)}, 404)
        except ApiError as e:
            self._send_json({"error": str(e)}, 502)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)


def main():
    ap = argparse.ArgumentParser(description="化学结构速查助手")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = ap.parse_args()

    # 已取消浏览器版：非打包（桌面版）环境下直接运行即退出。
    # 桌面版由 Electron 以打包模式调用，不受此限制。
    if not getattr(sys, "frozen", False) and os.environ.get("MEDCHEMHELPER_DEV") != "1":
        print("MedChemHelper 已取消浏览器版，请使用桌面版 MedChemHelper.exe。")
        print("（如需开发调试，请设置环境变量 MEDCHEMHELPER_DEV=1）")
        return

    os.makedirs(IMAGE_DIR, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print("=" * 56)
    print("  MedChemHelper 已启动")
    print(f"  打开: {url}")
    print(f"  RDKit 本地识别: {'已启用' if HAVE_RDKIT else '未启用（降级模式）'}")
    print("  按 Ctrl+C 停止")
    print("=" * 56)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
