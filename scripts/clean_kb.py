# -*- coding: utf-8 -*-
"""
知识库清洗（一次性迁移）：

  1. 从 drugs.json 删除 OCR 碎片/错字药名（如“如扎托司甫”“又称乙酰水杨酸”“唑类”），
     并删除重复 CID 的错字别名（万古氏素/喷他估辛等）。
  2. 把被删的真实药物别名（烟碱、度冷丁、雷米封等）补进 chinese_names.json，
     保证常用别名仍可检索且归一到正确结构。
  3. 清空 drug_pharm.json 中明显含章节标题/表格/剂量表的字段（target/action/mt），
     避免详情页显示“牛头不对马嘴”的 OCR 文本；同时删除已删药名的药理条目。

用法：
  python scripts/clean_kb.py
"""

import json
import os
import re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data")

# 1) OCR 句子碎片/错误结构，直接删除（其中真实药物别名由 chinese_names.json 承接）
FRAGMENT_NAMES = {
    "如扎托司甫", "如依那克林", "如麻黄碱或酷胺", "催化生成多巴", "故将其称之为烟碱",
    "如毛果芸香碱", "主要与二氧可待因酮", "B-苯乙胺", "如乙醚", "及三氟拉嗪",
    "减少纤溶酶原激活物抑制物", "及可供口服的珍米罗非班", "从尿喀啶脱氧核苷酸",
    "合成胸腺喀啶脱氧核苷酸", "LI-精氨酸", "如曲洛司坦", "抑制药奥达卡萘",
    "如特比茜芬和喀啶类", "针叶中提取巴卡丁", "素类抗凝药", "唑类",
}
# 2) OCR 错字别名：真实药物的错误写法，规范名已在药物库/词典中
TYPO_NAMES = {
    "又称司可林", "又名奴佛卡因", "又名赛罗卡因", "又称麻卡因", "又称大仑丁",
    "又名度冷丁", "又称乙酰水杨酸", "又名血清素", "又称雷米封",
    "万古氏素", "喷他估辛", "丁两诺啡", "氯两嗪", "丙米嗪", "葵巴比妥钠",
}
# 2b) OCR 错字药名 -> 规范中文名（改名后结构与药理条目一并迁移）
RENAME = {
    "氮磺洛尔": "氨磺洛尔",           # amosulalol
    "友沙溴铵": "戊沙溴铵",           # valethamate
    "氢溴酸东其营碱": "氢溴酸东莨菪碱",  # scopolamine hydrobromide
    "氢溴酸山苇著碱": "氢溴酸山莨菪碱",  # anisodamine hydrobromide
    "溴甲东其著碱": "溴甲东莨菪碱",     # scopolamine methylbromide
    "省化甲哌佐酯": "溴甲哌佐酯",      # mepenzolate
    "喷唆溴铵": "喷噻溴铵",           # penthienate
    "安贝毛贸": "安贝氯铵",           # ambenonium chloride
    "依酚毛铵": "依酚氯铵",           # edrophonium chloride
    "年美伐他洒": "美伐他汀",          # mevastatin
    "利舒脲": "利舒利特",             # lisuride
    "葵节胺": "苯茚胺",              # phenindamine
    "哌泊唆嗪": "哌泊噻嗪",           # pipotiazine
    "艾萘班特": "艾替班特",           # icatibant
    "称为奥格门汀": "奥格门汀",        # augmentin（阿莫西林/克拉维酸）
    "射剂为特治星": "哌拉西林他唑巴坦",  # tazocin
    "二钠": "帕米膦酸二钠",           # pamidronate disodium
    "阿仑腾酸钠": "阿仑膦酸钠",        # alendronate
    "雷洛背芬": "雷洛昔芬",           # raloxifene
    "磷酸略萘啶": "磷酸咯萘啶",        # pyronaridine
    "毛硝柳胺": "氯硝柳胺",           # niclosamide
    "吡酮": "吡喹酮",                # praziquantel
    "蜂萘派": "噻替派",              # thiotepa
    "硫鸟嘎叭": "硫鸟嘌呤",           # tioguanine
    "罗莫司河": "洛莫司汀",           # lomustine
    "双醋抉诺酮": "双醋炔诺醇",        # ethynodiol diacetate
    "磷酸氯唑": "磷酸氯喹",           # chloroquine
    "甲硫氧喀啶": "甲硫氧嘧啶",        # methylthiouracil
    "与氟毛西林": "氟氯西林",          # flucloxacillin
    "氮西林": "巴氨西林",             # bacampicillin
    "酝氨西林": "酞氨西林",            # talampicillin
    "持抗剂氟马西尼": "氟马西尼",       # flumazenil
    "雷米克林": "雷米吉仑",           # remikiren
    "可以被密胆碱": "密胆碱",          # hemicholine
    "丙酸倍毛米松": "丙酸倍氯米松",      # beclomethasone dipropionate
    "省已新": "溴己新",              # bromhexine
    "磷酸苯两哌林": "磷酸苯丙哌林",      # benproperine
    "丹草本": "丹蒽醌",              # danthron
    "酚本": "酚酞",                 # phenolphthalein
    "织样": "麦芽",                 # malt
    "的水溶性葛": "薁磺酸钠",         # azulene sulfonate sodium
    "氯叶酮": "氯噻酮",              # chlortalidone
    "氧化铵": "氯化铵",              # ammonium chloride
    "相继研究出艾多昔芬": "艾多昔芬",  # idoxifene
    "届洛萘芬": "屈洛昔芬",           # droloxifene
    "米普昔芬": "米泼昔芬",           # miproxifene
    "葛雷西蕊": "莫雷西嗪",           # moricizine
    "肝届晓": "肼屈嗪",              # hydralazine
    "氧磺肉服": "氯磺丙脲",           # chlorpropamide
    "的环茶已哌啶": "苯环己哌啶",      # phencyclidine
    "左旋昧唑": "左旋咪唑",           # levamisole
    "他药物还有布新洛尔": "布新洛尔",   # bucindolol
    "唑奉丁": "扎替啶",              # zaltidine
    "米星": "奈替米星",              # netilmicin
    "卡星": "阿贝卡星",              # arbekacin
    "基麦角新碱": "甲基麦角新碱",      # methylergometrine
    "匹莫葵": "匹莫苯丹",             # pimobendan
    "异布帕明": "异波帕明",           # ibopamine
    "氧普唆吨": "氯普噻吨",           # chlorprothixene
    "也称泰尔登": "泰尔登",           # tardan（氯普噻吨别名）
    "成为蒂巴因": "蒂巴因",           # thebaine
    "是非那西汀": "非那西汀",          # phenacetin
    "可与谷胱甘肽": "谷胱甘肽",        # glutathione
    "开发了阿分太尼": "阿芬太尼",      # alfentanil
    "右两氧分": "右丙氧芬",           # dextropropoxyphene
    "茶优卡因": "苯佐卡因",           # benzocaine
    "依萘卡因": "依替卡因",           # etidocaine
    "阿曲库匀": "阿曲库铵",           # atracurium
    "贝那替秦": "贝那替嗪",           # benactyzine
    "果氯匹定": "噻氯匹定",           # ticlopidine
    "受体持抗药拉米非班": "拉米非班",   # lamifiban
    "夫雷非班": "夫拉非班",           # fradafiban
    "水色素": "水蛭素",              # hirudin
    "匹可托安": "匹可酰胺",           # picotamide
    "奥沙西洋": "奥沙西泮",           # oxazepam
    "氟西洋": "氟西泮",              # flurazepam
    "替马西洋": "替马西泮",           # temazepam
    "夸西洋": "夸西泮",              # quazepam
    "氯氮草": "氯氮䓬",              # chlordiazepoxide
    "萘甲哗啉": "萘甲唑啉",           # naphazoline
    "枸橡酸氯米芬": "枸橼酸氯米芬",     # clomifene citrate
    "丙酸尝酮": "丙酸睾酮",           # testosterone propionate
    "氢可的松": "氟氢可的松",         # fludrocortisone
    "拉萘拉圳": "拉替拉韦",           # raltegravir
    "腾甲酸": "膦甲酸",              # foscarnet
    "与雷迪帕韦": "雷迪帕韦",         # ledipasvir
    "氟胞喀啶": "氟胞嘧啶",           # flucytosine
    "吡溴铵": "奥吡溴铵",            # oxypyrronium
    "艾司佐匹克隆": "右佐匹克隆",      # eszopiclone 重复条目合并
    "磷酸苯丙哌林": "苯丙哌林",        # benproperine 盐/碱重复合并
    "硫酸特布他林": "特布他林",        # terbutaline 盐/碱重复合并
    "硫酸沙丁胺醇": "沙丁胺醇",        # salbutamol 盐/碱重复合并
    "敌敌旦": "敌敌畏",              # DDVP
    "塔月": "塔崩",                 # tabun
    "多库铵": "多库氯铵",            # doxacurium chloride
    "克仑硫草": "克仑硫卓",           # clentiazem
    "唆洛尔": "吲哚洛尔",            # pindolol
    "米库铵": "米库氯铵",            # mivacurium 重复条目合并
    "蝇草醇": "蝇蕈醇",              # muscimol
    "氯化政珀胆碱": "氯化琥珀胆碱",    # suxamethonium chloride
    "醋甲哗胺": "醋甲唑胺",           # methazolamide
    "甲唑酮": "甲喹酮",              # methaqualone
    "茶磺顺阿曲库铵": "苯磺顺阿曲库铵",  # cisatracurium besilate
    "索普拉狗": "索普拉赞",           # soraprazan
    "茶丝肝": "苄丝肼",              # benserazide
    "萘勃龙": "替勃龙",              # tibolone
    "供口服用的有头孢叶辛酯": "头孢呋辛酯",   # cefuroxime axetil
    "可待因和器粟碱": "罂粟碱",        # papaverine
    "夫素和紫霉素": "紫霉素",          # viomycin
    "本类药中还有氟氧头孢": "氟氧头孢",  # flomoxef
    "类包括地拉韦定": "地拉韦定",       # delavirdine
    "通常用其糠酸酯": "二氯尼特糠酸酯",  # diloxanide furoate
    "霉素": "塞霉素",                # cethromycin
    "伯氨嘲": "伯氨喹",              # primaquine
    "头孢唑肝": "头孢唑肟",           # ceftizoxime
    "头孢备多": "头孢孟多",           # cefamandole
    "戊酸肉二醇": "戊酸雌二醇",        # estradiol valerate
    "醋氨茶硕": "醋氨苯砜",           # acedapsone
    "磺茶西林": "磺苄西林",           # sulbenicillin
    "酰螺旋霉素": "乙酰螺旋霉素",      # acetylspiramycin
    "第一个抗生素为硫霉素": "硫霉素",   # thienamycin
    "右两亚胺": "右雷佐生",           # dexrazoxane
    "的有效成分鬼白毒素": "鬼臼毒素",   # podophyllotoxin
    "的头孢呋辛酯": "头孢呋辛酯",       # cefuroxime axetil 重复合并
}
# 4) 分类修正（OCR 章节映射错误导致个别药物归错章节）
CATEGORY_FIX = {
    "吗啡": "镇痛", "曲马多": "镇痛", "哌替啶": "镇痛", "美沙酮": "镇痛",
    "罗通定": "镇痛", "罂粟碱": "镇痛", "蒂巴因": "镇痛", "二氢埃托啡": "镇痛",
    "布托啡诺": "镇痛", "延胡索乙素": "镇痛", "纳布啡": "镇痛",
    "枸橼酸芬太尼": "镇痛", "磷酸可待因": "镇痛",
    "三氟胸苷": "抗病毒", "洛沙平": "抗精神失常药", "阿莫沙平": "抗精神失常药",
    "胰岛素": "糖尿病", "氯磺丙脲": "糖尿病", "格列本脲": "糖尿病",
    "蝇蕈醇": "神经精神", "吲哚美辛": "解热镇痛抗炎药",
    "乙酰唑胺": "利尿", "醋甲唑胺": "利尿", "依他尼酸": "利尿",
    "氯噻酮": "利尿", "美托拉宗": "利尿", "坎利酮": "利尿",
    "山梨醇": "其他", "葡萄糖": "其他", "碘苷": "抗病毒",
    "雷米吉仑": "抗高血压药", "克林霉素": "抗生素",
    "依替米星": "抗生素", "地贝卡星": "抗生素", "奈替米星": "抗生素",
    "阿贝卡星": "抗生素", "异帕米星": "抗生素", "扎替啶": "消化",
    "索普拉赞": "消化", "去甲万古霉素": "抗生素", "杆菌肽": "抗生素",
    "吉米沙星": "抗生素", "乳糖酸红霉素": "抗生素", "依托红霉素": "抗生素",
    "硬脂酸红霉素": "抗生素", "乙酰吉他霉素": "抗生素", "乙酰螺旋霉素": "抗生素",
    "罗他霉素": "抗生素", "塞霉素": "抗生素", "戊酸雌二醇": "性激素类药及避孕药",
    "葵丙酸诺龙": "性激素类药及避孕药", "莫雷西嗪": "抗心律失常药",
    "波生坦": "抗高血压药", "氟烷": "全身麻醉药", "麻醉乙醚": "全身麻醉药",
    "神经安定镇痛合剂": "全身麻醉药", "水合氯醛": "镇静催眠药", "三唑仑": "镇静催眠药",
    "碱式碳酸铋": "消化", "次水杨酸铋": "消化", "硫酸钠": "其他",
    "促胃动素": "其他", "甘油": "其他", "坦罗莫司": "抗肿瘤",
    "尼卡地平": "心血管", "二氮嗪": "抗高血压药",
}
# 2c) 纯 OCR 碎片/药物类别条目（非具体药物），直接删除
EXTRA_FRAGMENTS = {
    "pyridin-2-yD", "-2-", "-受体蛋白-钙调素", "氯卡巴胆碱",
    "还有合成类似物震颤素", "廿碳烯酸类", "草醒类", "双肌类",
    "青霉素类", "头孢菌素类", "酮类", "成熟并从细胞内释放", "三唑类",
    "磺酸", "亚磺酰胺", "在胆碱乙酰转移酶", "加诱导型一氧化氮合酶",
    "降低脂肪细胞瘦素", "化和减弱兴奋性突触后电位", "降低环腺苷酸",
    "木脂素类和胶黏毒素", "N-甲基-D-天冬氨酸", "与百日咳毒素", "序列",
    "突触", "痛药", "抗生素", "氨酸脑啡肽", "使延胡索酸", "不能还原为琥珀酸",
}
# 3) 被删 OCR 名 -> 应保留的规范别名（写入 chinese_names.json，归一检索到正确结构）
#    别名条目使用被删条目的结构数据，但英文名替换为 PubChem 规范名以便在线查询
REMOVED_TO_ALIAS = {
    "故将其称之为烟碱": ("烟碱", "nicotine"),
    "如毛果芸香碱": ("毛果芸香碱", "pilocarpine"),
    "主要与二氧可待因酮": ("氢可酮", "hydrocodone"),
    "又称司可林": ("司可林", "suxamethonium"),
    "B-苯乙胺": ("β-苯乙胺", "phenylethylamine"),
    "又名奴佛卡因": ("奴佛卡因", "procaine"),
    "又名赛罗卡因": ("赛罗卡因", "lidocaine"),
    "又称麻卡因": ("麻卡因", "bupivacaine"),
    "又称大仑丁": ("大仑丁", "phenytoin"),
    "及三氟拉嗪": ("三氟拉嗪", "trifluoperazine"),
    "又名度冷丁": ("度冷丁", "pethidine"),
    "又名血清素": ("血清素", "serotonin"),
    "又称雷米封": ("雷米封", "isoniazid"),
    "如麻黄碱或酷胺": ("酪胺", "tyramine"),
    "催化生成多巴": ("多巴", "dopa"),
    "LI-精氨酸": ("精氨酸", "arginine"),
}
# 5) 词典条目缺 SMILES 的补齐（教科书标准结构，RDKit 已验证可解析）
DICT_SMILES_FIX = {
    "果糖": "OC[C@@H]1OC(O)(CO)[C@H](O)[C@@H]1O",
    "蔗糖": "OC[C@H]1O[C@@](CO)(O[C@H]2[C@H](O)[C@@H](O)[C@H](O)[C@@H](CO)O2)[C@@H](O)[C@@H](O)[C@@H]1O",
    "麦芽糖": "OC[C@H]1O[C@@H](O[C@@H]2[C@H](O)[C@@H](O)[C@H](O)O[C@@H]2CO)[C@H](O)[C@@H](O)[C@@H]1O",
    "乳糖": "OC[C@H]1O[C@@H](O[C@@H]2[C@H](O)[C@H](O)[C@@H](O)[C@H](O2)CO)[C@H](O)[C@@H](O)[C@@H]1O",
    "核糖": "OC[C@@H]1OC(O)[C@H](O)[C@@H]1O",
    "脱氧核糖": "OC[C@H]1OC(O)C[C@@H]1O",
    "胆固醇": "C[C@H](CCCC(C)C)[C@H]1CC[C@@H]2[C@@]1(C)CC[C@H]3[C@H]2CC=C4[C@@]3(C)CC[C@H](O)C4",
    "鸟嘌呤": "NC1=NC2=C(NC=N2)C(=O)N1",
    "尿酸": "O=C1NC(=O)NC2=C1NC(=O)N2",
}

PHARM_GARBAGE_RE = re.compile(
    r"第[一二三四五六七八九十百\d]+章|表\s*\d|\[药理作用\]|【体内过程】|"
    r"制剂及用法|结构式|分子式|[\u2500\u2502|]")
DOSE_RE = re.compile(r"片剂|注射剂|滴眼液|每次\s*\d|mg/d|mg/(kg|次)|μg|ug/kg|口服,每次|静注")


def is_bad_field(field, text):
    """字段是否含明显 OCR 碎片/章节表格文本。"""
    if not text:
        return False
    if field == "target" and len(text.strip()) > 60:
        return True
    if PHARM_GARBAGE_RE.search(text):
        return True
    if DOSE_RE.search(text) and len(text) > 120:
        return True
    return False


def main():
    drugs = json.load(open(os.path.join(DATA, "drugs.json"), encoding="utf-8"))
    pharm = json.load(open(os.path.join(DATA, "drug_pharm.json"), encoding="utf-8"))
    chinese = json.load(open(os.path.join(DATA, "chinese_names.json"), encoding="utf-8"))

    # 0) 先改名（结构条目与药理条目同步迁移）
    rename_map = {old: new for old, new in RENAME.items()}
    for d in drugs:
        if d["zh"] in rename_map:
            d["zh"] = rename_map[d["zh"]]
        if d["zh"] in CATEGORY_FIX:
            d["category"] = CATEGORY_FIX[d["zh"]]
    for old, new in rename_map.items():
        if old in pharm:
            if new in pharm:
                for k, v in pharm.pop(old).items():
                    if v and not pharm[new].get(k):
                        pharm[new][k] = v
            else:
                pharm[new] = pharm.pop(old)
    if "氯卡巴胆碱" in pharm:
        del pharm["氯卡巴胆碱"]

    remove = set()          # 要删除的中文名
    remove_rows = set()     # 要删除的行索引（同名重复条目只删后续行）
    by_cid = {}
    for i, d in enumerate(drugs):
        zh = d["zh"]
        cid = d.get("cid")
        if zh in FRAGMENT_NAMES or zh in TYPO_NAMES or zh in EXTRA_FRAGMENTS:
            remove.add(zh)
        if cid and cid in by_cid and by_cid[cid] != zh:
            # 同一 CID 出现多个中文名：保留规范名（可读、非碎片），删除其余
            if is_bad_name(zh) and not is_bad_name(by_cid[cid]):
                remove.add(zh)
            elif not is_bad_name(zh) and is_bad_name(by_cid[cid]):
                remove.add(by_cid[cid])
        elif cid:
            by_cid[cid] = zh

    # 同名重复条目（如两个“头孢氨苄”）：保留第一条，删除后续行
    seen_zh = {}
    for i, d in enumerate(drugs):
        zh = d["zh"]
        if zh in seen_zh:
            remove_rows.add(i)
        else:
            seen_zh[zh] = d

    new_drugs = [d for i, d in enumerate(drugs)
                 if d["zh"] not in remove and i not in remove_rows]
    removed_info = {d["zh"]: d for d in drugs if d["zh"] in remove}
    print("改名:", len(rename_map), "删除药名数:", len(remove), "删除重复行:", len(remove_rows))
    print(sorted(remove))

    # 别名补进词典（en/smiles/cid 复用被删条目的结构数据）
    added_alias = 0
    for removed_name, (alias, en) in REMOVED_TO_ALIAS.items():
        if alias in chinese:
            continue
        src = removed_info.get(removed_name)
        if not src:
            continue
        chinese[alias] = {
            "en": en,
            "smiles": src.get("smiles", ""),
            "cid": src.get("cid"),
            "formula": src.get("formula", ""),
            "mw": src.get("mw", ""),
            "iupac": src.get("iupac", ""),
            "inchikey": src.get("inchikey", ""),
        }
        added_alias += 1
    print("新增词典别名:", added_alias, list(REMOVED_TO_ALIAS.values())[:5], "...")

    # 词典条目补结构：优先静态表，其次按英文名匹配药物库
    n_fixed = 0
    drugs_by_en = {}
    for d in drugs:
        if d.get("en"):
            drugs_by_en.setdefault(d["en"].lower(), d)
    for zh, info in chinese.items():
        if info.get("smiles"):
            continue
        smi = DICT_SMILES_FIX.get(zh)
        src = None
        if not smi:
            src = drugs_by_en.get((info.get("en") or "").lower())
            smi = (src or {}).get("smiles") or ""
        if not smi:
            continue
        info["smiles"] = smi
        cid = info.get("cid") or (src or {}).get("cid")
        if cid:
            info["cid"] = cid
        for k in ("formula", "mw", "iupac", "inchikey"):
            if not info.get(k) and src and src.get(k):
                info[k] = src[k]
        n_fixed += 1
    print("词典补结构条目:", n_fixed)

    # 药理库：删除已删药名条目，清空受污染字段
    n_del = n_blank = 0
    for zh in list(pharm.keys()):
        if zh in remove:
            del pharm[zh]
            n_del += 1
            continue
        p = pharm[zh]
        for f in ("parent", "pharmacophore", "target", "action", "mt", "sar"):
            if is_bad_field(f, str(p.get(f) or "")):
                p[f] = ""
                n_blank += 1

    json.dump(new_drugs, open(os.path.join(DATA, "drugs.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(pharm, open(os.path.join(DATA, "drug_pharm.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(chinese, open(os.path.join(DATA, "chinese_names.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("drugs.json:", len(drugs), "->", len(new_drugs))
    print("drug_pharm.json:", len(pharm), "删除", n_del, "清空字段", n_blank)
    print("chinese_names.json:", len(chinese))


def is_bad_name(zh):
    if re.search(r"如|又称|又名|及|和|从|合成|减少|增加|主要与|抑制药|催化|故将其称之为|针叶中提取|类$", zh):
        return True
    if re.fullmatch(r"[\u4e00-\u9fa5]{1,10}", zh) is None:
        return True
    return False


if __name__ == "__main__":
    main()
