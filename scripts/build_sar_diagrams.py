"""Rebuild textbook-aligned SAR diagrams from explicit chemical structures.

The SVG files are generated from molecular graphs with RDKit.  Position labels
match the numbering used in the supplied medicinal-chemistry textbook; the
corresponding explanations live in data/drug_categories.json.
"""

from html import escape
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import rdDepictor
from rdkit.Chem.Draw import rdMolDraw2D


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

COLORS = {
    "required": (0.86, 0.24, 0.20, 0.24),
    "modifiable": (0.12, 0.47, 0.71, 0.22),
    "essential": (0.10, 0.62, 0.38, 0.24),
    "region": (0.49, 0.29, 0.84, 0.22),
    "optional": (0.93, 0.55, 0.12, 0.22),
}


def mapped_molecule(smiles):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SAR scaffold: {smiles}")
    mapped = {}
    for atom in mol.GetAtoms():
        map_number = atom.GetAtomMapNum()
        if map_number:
            mapped[map_number] = atom.GetIdx()
            atom.SetAtomMapNum(0)
    return mol, mapped


def apply_notes(mol, notes):
    for atom_index, note in notes.items():
        mol.GetAtomWithIdx(atom_index).SetProp("atomNote", str(note))


def render_svg(filename, title, description, mol, notes, groups, atom_labels=None):
    apply_notes(mol, notes)
    rdDepictor.Compute2DCoords(mol)
    mol = rdMolDraw2D.PrepareMolForDrawing(mol, addChiralHs=True, wedgeBonds=True)
    for atom in mol.GetAtoms():
        if atom.HasProp("_CIPCode"):
            atom.ClearProp("_CIPCode")

    highlight_atoms = []
    highlight_colors = {}
    for group_name, atom_indices in groups:
        for atom_index in atom_indices:
            if atom_index not in highlight_atoms:
                highlight_atoms.append(atom_index)
            highlight_colors[atom_index] = COLORS[group_name]

    drawer = rdMolDraw2D.MolDraw2DSVG(720, 330)
    options = drawer.drawOptions()
    options.useBWAtomPalette()
    options.clearBackground = False
    options.prepareMolsBeforeDrawing = False
    # Keep wedge/dash stereobonds, but omit automatic (R)/(S) labels because
    # they compete with the textbook's own position numbering.
    options.addStereoAnnotation = False
    options.atomHighlightsAreCircles = True
    options.fillHighlights = True
    options.bondLineWidth = 2.2
    options.annotationFontScale = 0.88
    options.minFontSize = 13
    options.maxFontSize = 24
    if atom_labels:
        for atom_index, label in atom_labels.items():
            options.atomLabels[atom_index] = label

    drawer.DrawMolecule(
        mol,
        highlightAtoms=highlight_atoms,
        highlightAtomColors=highlight_colors,
    )
    drawer.FinishDrawing()
    molecule_svg = drawer.GetDrawingText()
    marker = "<!-- END OF HEADER -->"
    body = molecule_svg[molecule_svg.index(marker) + len(marker):molecule_svg.rfind("</svg>")]

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 390" role="img" aria-labelledby="title desc">
<title id="title">{escape(title)}</title>
<desc id="desc">{escape(description)}</desc>
<rect width="720" height="390" rx="12" fill="#ffffff"/>
<rect width="720" height="58" fill="#f0f7ff"/>
<rect width="7" height="58" fill="#2563eb"/>
<text x="25" y="36" font-family="Microsoft YaHei,Segoe UI,sans-serif" font-size="22" font-weight="700" fill="#0f172a">{escape(title)}</text>
<g transform="translate(0 58)">{body}</g>
</svg>'''
    (STATIC / filename).write_text(svg, encoding="utf-8")


def build_penicillin():
    mol, m = mapped_molecule(
        "C[C:3]1(C)[C@@H:2](C(=O)O)[N:1]2[C:7](=O)[C@@H:6](NC(=O)[*:8])[C@@H:5]2[S:4]1"
    )
    render_svg(
        "sar-penicillin.svg",
        "青霉素母核（penam）与位点编号",
        "准确的青霉烷母核、1至7位编号以及6位通用酰氨基侧链R。",
        mol,
        {m[n]: n for n in range(1, 8)},
        [
            ("essential", [m[2], m[7]]),
            ("modifiable", [m[6], m[8]]),
            ("optional", [m[3], m[4]]),
        ],
        {m[8]: "R"},
    )


def build_cephalosporin():
    mol, m = mapped_molecule(
        "[*:1]C(=O)N[C@@H:2]1C(=O)N2C(C(=O)O)=C([CH2:4]OC(C)=O)C[S:3][C@H]12"
    )
    render_svg(
        "sar-cephalosporin.svg",
        "头孢菌素母核（cephem）与 I—IV 区域",
        "准确的头孢烯母核，标出教材定义的I至IV构效区域。",
        mol,
        {m[1]: "I", m[2]: "II", m[3]: "III", m[4]: "IV"},
        [
            ("modifiable", [m[1]]),
            ("region", [m[2]]),
            ("essential", [m[3]]),
            ("optional", [m[4]]),
        ],
        {m[1]: "R"},
    )


def build_tetracycline():
    mol = Chem.MolFromSmiles(
        "C[C@@]1([C@H]2C[C@H]3[C@@H](C(=O)C(=C([C@]3(C(=O)C2=C(C4=C1C=CC=C4O)O)O)O)C(=O)N)N(C)C)O"
    )
    positions = {1: 6, 2: 8, 3: 9, 4: 5, 5: 3, 6: 1, 7: 17, 8: 18, 9: 19, 10: 20, 11: 11, 12: 14}
    render_svg(
        "sar-tetracycline.svg",
        "四环素母体结构与 1—12 位编号",
        "四环稠合母体的准确键线式，标出教材使用的1至12位。",
        mol,
        {atom_index: position for position, atom_index in positions.items()},
        [
            ("required", [positions[n] for n in range(1, 5)]),
            ("modifiable", [positions[n] for n in range(5, 10)]),
            ("essential", [positions[11], positions[12]]),
        ],
    )


def build_erythromycin():
    mol = Chem.MolFromSmiles(
        "CC[C@@H]1[C@@]([C@@H]([C@H](C(=O)[C@@H](C[C@@]([C@@H]([C@H]([C@@H]([C@H](C(=O)O1)C)O[C@H]2C[C@@]([C@H]([C@@H](O2)C)O)(C)OC)C)O[C@H]3[C@@H]([C@H](C[C@H](O3)C)N(C)C)O)(C)O)C)C)O)(C)O"
    )
    positions = {1: 15, 2: 14, 3: 13, 4: 12, 5: 11, 6: 10, 7: 9, 8: 8, 9: 6, 10: 5, 11: 4, 12: 3, 13: 2}
    render_svg(
        "sar-erythromycin.svg",
        "红霉素 14 元大环内酯与 1—13 位编号",
        "红霉素完整结构，保留大环内酯、去氧氨基糖和克拉定糖。",
        mol,
        {atom_index: position for position, atom_index in positions.items()},
        [
            ("region", list(positions.values())),
            ("required", [positions[9]]),
            ("modifiable", [positions[6]]),
            ("essential", [33, 34, 35, 36, 37, 38, 40]),
            ("optional", [20, 21, 22, 23, 24, 25]),
        ],
    )


def build_sulfonamide():
    mol, m = mapped_molecule("[NH2:4]c1ccc(S(=O)(=O)[NH:1][*:5])cc1")
    render_svg(
        "sar-sulfonamide.svg",
        "对氨基苯磺酰胺母核（N⁴ / N¹）",
        "磺胺类通用母核，标出对位氨基N4、磺酰胺氮N1和单取代基R。",
        mol,
        {m[4]: "N4", m[1]: "N1"},
        [
            ("essential", [m[4]]),
            ("required", [m[1]]),
            ("modifiable", [m[5]]),
        ],
        {m[5]: "R"},
    )


def build_quinolone():
    mol, m = mapped_molecule(
        "[*:101][N:1]1[C:2]([*:102])=[C:3](C(=O)O)[C:4](=O)C2=[C:5]([*:105])[C:6]([*:106])=[C:7]([*:107])[C:8]([*:108])=C21"
    )
    dummy_labels = {m[101]: "R1", m[102]: "R2", m[105]: "R5", m[106]: "R6", m[107]: "R7", m[108]: "R8"}
    render_svg(
        "sar-quinolone.svg",
        "4-喹诺酮-3-羧酸母核与 1—8 位编号",
        "喹诺酮类通用母核，准确标出1至8位及可变取代基。",
        mol,
        {m[n]: n for n in range(1, 9)},
        [
            ("essential", [m[3], m[4]]),
            ("required", [m[2]]),
            ("modifiable", [m[1], m[5], m[6], m[7], m[8]]),
        ],
        dummy_labels,
    )


def main():
    build_penicillin()
    build_cephalosporin()
    build_tetracycline()
    build_erythromycin()
    build_sulfonamide()
    build_quinolone()
    print("Rebuilt 6 textbook-aligned SAR diagrams.")


if __name__ == "__main__":
    main()
