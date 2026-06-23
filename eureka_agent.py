from __future__ import annotations

import argparse
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


BASE_DIR = Path(__file__).resolve().parent
LIBRARY_DIR = BASE_DIR / "library"
PAPER_FIGURE_DIR = LIBRARY_DIR / "paper_figures"
ZOTERO_DIGEST_PATH = LIBRARY_DIR / "zotero_digest.json"
WORKFLOW_DIR = BASE_DIR / "agent_workspace"
EUREKA_PROFILE_PATH = WORKFLOW_DIR / "eureka_profile.json"


NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


EXTERNAL_SEED_REFERENCES = [
    {
        "title": "Motion of liquid and stabilising particles in individual liquid aluminium alloy films",
        "year": 2020,
        "doi": "10.1007/s10853-020-05007-5",
        "link": "https://link.springer.com/article/10.1007/s10853-020-05007-5",
        "keywords": "rigid particles; liquid films; Plateau borders; trapping; particle motion",
        "summary": "2020 后的颗粒-液膜运动实验证据，可作为硬质小球在液膜/PB 附近卡滞、脱困、随流运动的类比。",
        "origin": "web_seed",
    },
    {
        "title": "Particles, Drops, and Bubbles Moving Across Sharp Interfaces and Stratified Layers",
        "year": 2020,
        "doi": "10.1146/annurev-fluid-010719-060139",
        "link": "https://www.annualreviews.org/doi/10.1146/annurev-fluid-010719-060139",
        "keywords": "review; particles; drops; bubbles; interfaces; transport",
        "summary": "综述刚性/可变形物体穿越界面时的阻力、界面变形、滞留和输运机制。",
        "origin": "web_seed",
    },
    {
        "title": "A review of aqueous foam in microscale",
        "year": 2018,
        "doi": "10.1016/j.cis.2018.04.004",
        "link": "https://www.sciencedirect.com/science/article/abs/pii/S0001868617305286",
        "keywords": "review; aqueous foam; microscale; Plateau borders; films; particles; droplets",
        "summary": "泡沫微尺度综述，覆盖 PB、液膜、节点中的流动以及颗粒/油滴对稳定性的影响。",
        "origin": "web_seed",
    },
    {
        "title": "Drop coalescence and liquid flow in a single Plateau border",
        "year": 2015,
        "doi": "10.1103/PhysRevE.91.053008",
        "link": "https://pubmed.ncbi.nlm.nih.gov/26066250/",
        "keywords": "droplet; Plateau border; coalescence; inertial imbibition; viscous regime",
        "summary": "单 PB 注入液滴后的液体重分布、惯性/黏性分区和并合过程，可对照液滴类输运。",
        "origin": "web_seed",
    },
    {
        "title": "Geometric dispersion of unattached particles in foams",
        "year": 2007,
        "doi": "10.1016/j.colsurfa.2007.04.028",
        "link": "https://www.sciencedirect.com/science/article/abs/pii/S0927775707003111",
        "keywords": "particles; foams; Plateau border network; geometric dispersion; drainage",
        "summary": "颗粒在 PB 网络中的几何扩散模型，适合为多通道/非单 PB 迁移提供背景。",
        "origin": "web_seed",
    },
]


RECENT_EXTERNAL_REFERENCES = [
    {
        "title": "New insights into antibubble formation by single drop impact on a same-liquid pool",
        "year": 2024,
        "doi": "10.1016/j.jcis.2024.02.007",
        "link": "https://www.sciencedirect.com/science/article/pii/S0021979724002431",
        "keywords": "antibubble formation; drop impact; controlled generation; surfactant-stabilized antibubbles",
        "summary": "近 5 年反气泡形成机制文献，可用于更新生成窗口、撞击条件和稳定性判断。",
        "origin": "recent_external",
    },
    {
        "title": "Antibubble column: A mean to measure and enhance liquid-gas mass transfer through surfactant-laden interfaces",
        "year": 2024,
        "doi": "10.1016/j.cej.2024.153276",
        "link": "https://www.sciencedirect.com/science/article/abs/pii/S1385894724047648",
        "keywords": "antibubble column; mass transfer; surfactant-laden interfaces; gas-liquid transport",
        "summary": "反气泡应用与传质方向的新文献，可为未来把 PB 输运和传质/寿命联系起来提供出口。",
        "origin": "recent_external",
    },
    {
        "title": "Settling velocity variation induced by a sphere moving across a two-layer stratified fluid with different rheological characteristics",
        "year": 2023,
        "doi": "10.1039/D2RA08286A",
        "link": "https://pubs.rsc.org/en/content/articlehtml/2023/ra/d2ra08286a",
        "keywords": "sphere; stratified fluids; interface crossing; rheology; settling velocity; drag coefficient",
        "summary": "硬质小球跨界面/分层体系的速度变化文献，可辅助解释小球遇到液膜/界面时的阻滞或加速。",
        "origin": "recent_external",
    },
    {
        "title": "Solid particles moving parallel to a deformable liquid-liquid interface in a microchannel: migration forces",
        "year": 2022,
        "doi": "10.1017/jfm.2022.683",
        "link": "https://www.cambridge.org/core/journals/journal-of-fluid-mechanics/article/solid-particles-moving-parallel-to-a-deformable-liquidliquid-interface-in-a-microchannel-migration-forces/E8D4A73131317001C68662B8E6409153",
        "keywords": "solid particles; deformable liquid-liquid interface; microchannel; migration forces",
        "summary": "硬质颗粒近可变形界面运动的力学模型候选，适合给小球-液膜相互作用提供横向迁移/界面变形视角。",
        "origin": "recent_external",
    },
    {
        "title": "On the interaction between a rising bubble and a settling particle",
        "year": 2024,
        "doi": "10.1017/jfm.2024.686",
        "link": "https://www.cambridge.org/core/journals/journal-of-fluid-mechanics/article/on-the-interaction-between-a-rising-bubble-and-a-settling-particle/88E11BA25B79C387D0065333136A606C",
        "keywords": "bubble-particle interaction; settling particle; interface-mediated hydrodynamics",
        "summary": "泡-颗粒相互作用新文献，可为硬质小球与液膜/气液界面附近的耦合轨迹提供参照。",
        "origin": "recent_external",
    },
    {
        "title": "Impulse-driven release of gas-encapsulated drops",
        "year": 2024,
        "doi": "10.1017/jfm.2024.1124",
        "link": "https://www.cambridge.org/core/journals/journal-of-fluid-mechanics/article/impulsedriven-release-of-gasencapsulated-drops/82897E04B34494D5F87FA958FE2D1160",
        "keywords": "gas-encapsulated drops; antibubble dynamics; impulse-driven release; encapsulation",
        "summary": "气膜包覆液滴动力学近年文献，可服务反气泡/包覆体失稳、释放和破裂方向。",
        "origin": "recent_external",
    },
    {
        "title": "Scaling law for the kinetics of water imbibition in polydisperse foams",
        "year": 2022,
        "doi": "",
        "link": "https://pmc.ncbi.nlm.nih.gov/articles/PMC9042101/",
        "keywords": "foam imbibition; Plateau borders; capillary pressure; liquid transport; scaling law",
        "summary": "泡沫 PB 网络液体吸入/输运的尺度律文献，可用于未来把单 Case 扩展到 PB 网络相图。",
        "origin": "recent_external",
    },
]


PB_PARTICLE_FOCUS_REFERENCES = [
    {
        "title": "A flow velocity dependence of dynamic surface tension in Plateau borders of foam",
        "year": 2020,
        "doi": "10.1016/j.jcis.2020.04.028",
        "link": "https://www.sciencedirect.com/science/article/abs/pii/S0021979720304595",
        "keywords": "Plateau border; foam drainage; dynamic surface tension; flow velocity; interfacial contamination",
        "summary": "PB 内局部流速与界面状态耦合，适合提醒 Eureka：颗粒轨迹异常不能只按自由落体解释，还要检查 PB/液膜内的界面流动与污染。",
        "origin": "pb_particle_focus",
    },
    {
        "title": "Critical bubble diameters and Plateau border dimensions for drainage in aqueous xanthan foams",
        "year": 2020,
        "doi": "10.1016/j.colsurfa.2020.125682",
        "link": "https://www.sciencedirect.com/science/article/abs/pii/S0927775720312608",
        "keywords": "Plateau borders; foam drainage; particle obstruction; bubble diameter; drainage transition",
        "summary": "PB 尺寸、泡径与排液状态会改变通道输运，可用于给硬质小球实验建立几何约束与通道尺度检查。",
        "origin": "pb_particle_focus",
    },
    {
        "title": "Solid particles moving parallel to a deformable liquid-liquid interface in a microchannel: migration forces",
        "year": 2022,
        "doi": "10.1017/jfm.2022.683",
        "link": "https://www.cambridge.org/core/journals/journal-of-fluid-mechanics/article/solid-particles-moving-parallel-to-a-deformable-liquidliquid-interface-in-a-microchannel-migration-forces/E8D4A73131317001C68662B8E6409153",
        "keywords": "solid particles; deformable interface; migration forces; microchannel; interface-mediated hydrodynamics",
        "summary": "硬质颗粒近界面运动的力学参照，用于 Eureka 判断小球靠近液膜/PB 时的横向迁移、贴附或偏转，而不直接改处理参数。",
        "origin": "pb_particle_focus",
    },
    {
        "title": "On the interaction between a rising bubble and a settling particle",
        "year": 2024,
        "doi": "10.1017/jfm.2024.686",
        "link": "https://www.cambridge.org/core/journals/journal-of-fluid-mechanics/article/on-the-interaction-between-a-rising-bubble-and-a-settling-particle/88E11BA25B79C387D0065333136A606C",
        "keywords": "bubble-particle interaction; settling particle; interface-mediated hydrodynamics; collision; trajectory coupling",
        "summary": "泡-颗粒相互作用近年文献，用于提醒 Eureka：小球与弯月面/气液界面相遇时，轨迹耦合和局部流场比单颗粒沉降更重要。",
        "origin": "pb_particle_focus",
    },
]


TITLE_KEYS = ("题目", "文献", "文献名", "title", "paper", "article")
YEAR_KEYS = ("年份", "year", "date")
DOI_KEYS = ("doi", "doi/主页链接", "主页链接")
LINK_KEYS = ("下载链接", "下载/主页链接", "link", "url", "主页")
KEYWORD_KEYS = ("关键词", "关键阅读点", "逻辑层级", "子问题定位", "研究对象/场景")
METHOD_KEYS = ("研究方法", "实验/数据模块", "推荐做法")
FINDING_KEYS = ("主要结果和结论", "主要结论", "关键公式/无量纲数/判据", "重要公式/无量纲数/判据", "对本课题的作用", "对本课题的用法")


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _simple_slug(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "_", value)
    return re.sub(r"_+", "_", value).strip("_")[:90]


def _figure_url_for_reference(ref: dict[str, Any]) -> str:
    PAPER_FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    candidates = [
        _simple_slug(_text(ref.get("doi"))),
        _simple_slug(_text(ref.get("title"))),
    ]
    files = [path for path in PAPER_FIGURE_DIR.glob("*") if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
    for candidate in candidates:
        if not candidate:
            continue
        for path in files:
            stem = _simple_slug(path.stem)
            if candidate in stem or stem in candidate:
                return "/" + path.resolve().relative_to(BASE_DIR.resolve()).as_posix()
    try:
        from paper_figure_fetcher import figure_path_for, make_summary_card

        target = figure_path_for(ref)
        if not target.exists():
            make_summary_card(ref, target)
        return "/" + target.resolve().relative_to(BASE_DIR.resolve()).as_posix()
    except Exception:
        return ""
    return ""


def _norm_key(value: str) -> str:
    return re.sub(r"\s+", "", value.strip().lower())


def _cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "s":
        value = cell.findtext("main:v", namespaces=NS)
        if value is None:
            return ""
        try:
            return shared_strings[int(value)]
        except (ValueError, IndexError):
            return value
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//main:t", NS)).strip()
    return (cell.findtext("main:v", namespaces=NS) or "").strip()


def _column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    index = 0
    for ch in letters:
        index = index * 26 + ord(ch) - ord("A") + 1
    return max(index - 1, 0)


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    values = []
    for item in root.findall("main:si", NS):
        values.append("".join(node.text or "" for node in item.findall(".//main:t", NS)).strip())
    return values


def _sheet_paths(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rel_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rels = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rel_root.findall("pkgrel:Relationship", NS)
        if "Id" in rel.attrib and "Target" in rel.attrib
    }
    sheets = []
    for sheet in workbook.findall("main:sheets/main:sheet", NS):
        name = sheet.attrib.get("name", "Sheet")
        rel_id = sheet.attrib.get(f"{{{NS['rel']}}}id")
        target = rels.get(rel_id or "")
        if not target:
            continue
        target = target.lstrip("/")
        target_path = target if target.startswith("xl/") else f"xl/{target}"
        sheets.append((name, target_path))
    return sheets


def _read_xlsx(path: Path) -> list[dict[str, Any]]:
    records = []
    with zipfile.ZipFile(path) as zf:
        shared = _shared_strings(zf)
        for sheet_name, sheet_path in _sheet_paths(zf):
            try:
                root = ET.fromstring(zf.read(sheet_path))
            except KeyError:
                continue
            rows: list[list[str]] = []
            for row in root.findall(".//main:sheetData/main:row", NS):
                values: list[str] = []
                for cell in row.findall("main:c", NS):
                    idx = _column_index(cell.attrib.get("r", "A1"))
                    while len(values) <= idx:
                        values.append("")
                    values[idx] = _cell_text(cell, shared)
                if any(value.strip() for value in values):
                    rows.append(values)
            records.extend(_rows_to_records(path.name, sheet_name, rows))
    return records


def _read_pptx_slides(path: Path) -> list[dict[str, Any]]:
    slides: list[dict[str, Any]] = []
    try:
        with zipfile.ZipFile(path) as zf:
            slide_names = sorted(
                [name for name in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name)],
                key=lambda name: int(re.search(r"slide(\d+)\.xml", name).group(1)),
            )
            for idx, name in enumerate(slide_names, start=1):
                root = ET.fromstring(zf.read(name))
                texts = [node.text.strip() for node in root.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}t") if node.text and node.text.strip()]
                joined = " ".join(texts)
                if joined:
                    slides.append({"file": path.name, "slide": idx, "text": joined})
    except Exception:
        return []
    return slides


def _unique_library_sources(library_dir: Path) -> list[Path]:
    """Return library files while collapsing duplicated PPT exports by filename."""
    ranked: dict[tuple[str, str], tuple[tuple[int, float], Path]] = {}
    for path in sorted(library_dir.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix == ".pptx":
            key = ("pptx", path.name.lower())
        else:
            try:
                rel_key = path.relative_to(library_dir).as_posix().lower()
            except ValueError:
                rel_key = path.name.lower()
            key = ("file", rel_key)
        try:
            modified = path.stat().st_mtime
        except OSError:
            modified = 0.0
        # Prefer the root-level copy of a duplicated deck, then the newer copy.
        rank = (1 if path.parent == library_dir else 0, modified)
        if key not in ranked or rank > ranked[key][0]:
            ranked[key] = (rank, path)
    return [item[1] for item in sorted(ranked.values(), key=lambda item: item[1].as_posix().lower())]


def load_group_meeting_context(library_dir: Path = LIBRARY_DIR) -> dict[str, Any]:
    slides: list[dict[str, Any]] = []
    text_notes: list[dict[str, Any]] = []
    for path in _unique_library_sources(library_dir):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix == ".pptx":
            slides.extend(_read_pptx_slides(path))
        elif suffix in {".md", ".txt"}:
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            if text:
                text_notes.append({"file": path.name, "text": text[:5000]})

    keywords = ["相图", "phase", "Re", "We", "Ca", "Bo", "Oh", "无量纲", "PB", "Plateau", "液膜", "小球", "颗粒", "液滴", "反气泡"]
    candidates = []
    for slide in slides:
        text = slide["text"]
        hit_count = sum(1 for key in keywords if key.lower() in text.lower())
        if hit_count:
            candidates.append(
                {
                    "file": slide["file"],
                    "slide": slide["slide"],
                    "hits": hit_count,
                    "text": text[:360],
                }
            )
    candidates.sort(key=lambda item: (item["hits"], -item["slide"]), reverse=True)
    return {
        "file_count": len({slide["file"] for slide in slides}) + len(text_notes),
        "slide_count": len(slides),
        "slides": slides[:120],
        "text_notes": text_notes,
        "phase_candidates": candidates[:8],
    }


def _group_meeting_report_mode(group: dict[str, Any]) -> dict[str, Any]:
    slides = group.get("slides", [])
    evidence_terms = [
        "科学问题",
        "关键缺口",
        "研究主题",
        "文献证据链",
        "相图",
        "准则",
        "We-Bo",
        "t/t",
        "无量纲",
        "Plateau border",
        "包覆液滴",
        "平行输运",
    ]
    evidence = []
    for slide in slides:
        text = _text(slide.get("text"))
        hit_count = sum(1 for term in evidence_terms if term.lower() in text.lower())
        if hit_count:
            evidence.append(
                {
                    "file": slide.get("file"),
                    "slide": slide.get("slide"),
                    "hits": hit_count,
                    "text": text[:420],
                }
            )
    evidence.sort(key=lambda item: (item["hits"], -int(item.get("slide") or 0)), reverse=True)

    style = [
        {
            "title": "问题先行",
            "detail": "汇报开头先把实验现象翻译成科学问题，再给出文献缺口和研究主题。",
        },
        {
            "title": "证据链叙事",
            "detail": "从 PB/泡沫网络输运、局部毛细吸入、第三相受限输运，推进到包覆态生成与反气泡转化。",
        },
        {
            "title": "相图与准则收束",
            "detail": "关键结果最好落在 We-Bo、t/t、Re、R、|v|、|a|/g 等相图或判据坐标上。",
        },
        {
            "title": "现象分型",
            "detail": "把自由飞行、界面导向滑移、卡滞/脱困、误识别等事件拆开，再进入拟合和结论。",
        },
    ]
    conclusions = [
        "当前最好的总叙事不是单纯“生成反气泡”，而是“Plateau border 与液膜网络中的包覆态生成和输运”。",
        "PPT 中已形成清晰缺口：PB/液膜可输运，但包覆液滴在其中的平行输运图谱、稳定性与机制仍不清楚。",
        "硬质小球数据应作为对照对象：它能把刚体颗粒受限输运、界面/弯月面作用和液滴包覆态输运区分开。",
        "周四检查时，优先展示“论文进度、代表性 Case、相图雏形、文献雷达、Quill 草稿”，少展示底层开关和工程细节。",
        "下一批硬小球-液膜相互作用录像，需要更强的 ROI/事件分段质检，尤其惩罚左侧液体运动导致的误识别。",
    ]
    inspection_route = [
        "总控台：先看论文进度条、Eureka 检查摘要和今日备忘。",
        "数据处理：展示最高分结果，说明 Sisyphus 自动处理、Franklin 质检、Eureka 独立解释。",
        "结果相图：用 R、|v|、|a|/g 说明相图正在从视频自动提取。",
        "文献调研：展示近五年文献卡片和组会 PPT 提取出的科学问题。",
        "文章撰写：展示 Quill 只写已完成内容，未知机制留空，符合 PRL/JFM 风格草稿。",
    ]
    return {
        "style": style,
        "key_conclusions": conclusions,
        "inspection_route": inspection_route,
        "evidence_slides": evidence[:6],
    }



def _rows_to_records(source_file: str, sheet_name: str, rows: list[list[str]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    header_index = 0
    best_score = -1
    known = {_norm_key(key) for key in TITLE_KEYS + YEAR_KEYS + DOI_KEYS + LINK_KEYS + KEYWORD_KEYS + METHOD_KEYS + FINDING_KEYS}
    for idx, row in enumerate(rows[:10]):
        score = sum(2 for value in row if _norm_key(value) in known) + sum(1 for value in row if value.strip())
        if score > best_score:
            header_index = idx
            best_score = score
    raw_headers = rows[header_index]
    headers: list[str] = []
    seen: dict[str, int] = {}
    for idx, header in enumerate(raw_headers):
        name = header.strip() or f"col_{idx + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 1
        headers.append(name)
    out = []
    for row in rows[header_index + 1 :]:
        record = {headers[i] if i < len(headers) else f"col_{i + 1}": row[i].strip() for i in range(len(row))}
        if any(record.values()):
            record["_source_file"] = source_file
            record["_sheet"] = sheet_name
            out.append(record)
    return out


def _find_by_keys(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    normalized = {_norm_key(key): key for key in record}
    for wanted in keys:
        wanted_norm = _norm_key(wanted)
        for norm, original in normalized.items():
            if wanted_norm and wanted_norm in norm:
                value = _text(record.get(original))
                if value:
                    return value
    return ""


def _find_doi(text: str) -> str:
    match = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", text, flags=re.I)
    return match.group(0).rstrip(".,;，。；") if match else ""


def _find_year(text: str) -> int | None:
    years = [int(item) for item in re.findall(r"\b(20\d{2}|19\d{2})\b", text)]
    valid = [year for year in years if year >= 2000]
    return max(valid) if valid else None


def _find_link(text: str) -> str:
    match = re.search(r"https?://[^\s，,;；)）]+", text)
    return match.group(0) if match else ""


def normalize_literature_record(record: dict[str, Any]) -> dict[str, Any] | None:
    row_text = " | ".join(_text(value) for key, value in record.items() if not key.startswith("_"))
    title = _find_by_keys(record, TITLE_KEYS)
    if not title:
        for value in record.values():
            text = _text(value)
            if len(text) >= 12 and not text.startswith("http"):
                title = text
                break
    if not title:
        return None

    year_text = _find_by_keys(record, YEAR_KEYS)
    year = _find_year(year_text) or _find_year(row_text)
    doi_text = _find_by_keys(record, DOI_KEYS) or row_text
    link_text = _find_by_keys(record, LINK_KEYS) or row_text
    doi = _find_doi(doi_text)
    link = _find_link(link_text)

    return {
        "title": title,
        "year": year,
        "doi": doi,
        "link": link,
        "keywords": _find_by_keys(record, KEYWORD_KEYS),
        "method": _find_by_keys(record, METHOD_KEYS),
        "summary": _find_by_keys(record, FINDING_KEYS),
        "source_file": record.get("_source_file"),
        "sheet": record.get("_sheet"),
        "origin": "library",
    }


def load_zotero_digest(library_dir: Path = LIBRARY_DIR) -> dict[str, Any]:
    path = library_dir / "zotero_digest.json"
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            digest = json.load(f)
    except Exception as exc:  # noqa: BLE001 - keep dashboard generation resilient.
        return {"_load_error": str(exc), "_path": str(path)}
    if isinstance(digest, dict):
        digest["_path"] = str(path)
        return digest
    return {"_load_error": "Zotero digest is not a JSON object.", "_path": str(path)}


def summarize_zotero_digest(digest: dict[str, Any]) -> dict[str, Any]:
    if not digest:
        return {"available": False}
    summary = digest.get("summary", {}) if isinstance(digest.get("summary"), dict) else {}
    topic_counts = digest.get("topics", {}).get("counts", {}) if isinstance(digest.get("topics"), dict) else {}
    top_topics = [
        {"topic": topic, "count": count}
        for topic, count in list(topic_counts.items())[:8]
    ]
    return {
        "available": "_load_error" not in digest,
        "path": digest.get("_path"),
        "generated_at": digest.get("generated_at"),
        "unique_entry_count": summary.get("unique_entry_count", 0),
        "recent_2020_plus_count": summary.get("recent_2020_plus_count", 0),
        "doi_count": summary.get("doi_count", 0),
        "pdf_count": summary.get("pdf_count", 0),
        "read_status_counts": summary.get("read_status_counts", {}),
        "top_topics": top_topics,
        "load_error": digest.get("_load_error"),
    }


def load_literature_corpus(library_dir: Path = LIBRARY_DIR, include_seed: bool = True) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for path in sorted(library_dir.glob("*")):
        if path.suffix.lower() == ".xlsx":
            for record in _read_xlsx(path):
                entry = normalize_literature_record(record)
                if entry:
                    entries.append(entry)
        elif path.suffix.lower() in {".md", ".txt", ".csv"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                if len(line.strip()) < 12:
                    continue
                entries.append(
                    {
                        "title": line.strip()[:260],
                        "year": _find_year(line),
                        "doi": _find_doi(line),
                        "link": _find_link(line),
                        "keywords": "",
                        "method": "",
                        "summary": "",
                        "source_file": path.name,
                        "sheet": None,
                        "origin": "library",
                    }
                )

    if include_seed:
        known_doi = {entry.get("doi") for entry in entries if entry.get("doi")}
        known_titles = {str(entry.get("title", "")).lower() for entry in entries}
        for seed in [*EXTERNAL_SEED_REFERENCES, *RECENT_EXTERNAL_REFERENCES, *PB_PARTICLE_FOCUS_REFERENCES]:
            if seed["doi"] in known_doi or seed["title"].lower() in known_titles:
                continue
            entries.append(seed.copy())

    entries = [entry for entry in entries if (entry.get("year") is None or int(entry["year"]) >= 2000)]
    zotero_digest = load_zotero_digest(library_dir)
    summary = summarize_corpus(entries)
    if zotero_digest:
        summary["zotero"] = summarize_zotero_digest(zotero_digest)
    corpus = {
        "entries": entries,
        "summary": summary,
        "group_meetings": load_group_meeting_context(library_dir),
        "zotero": zotero_digest,
    }
    corpus["research_digest"] = build_research_digest(corpus)
    return corpus


def summarize_corpus(entries: list[dict[str, Any]]) -> dict[str, Any]:
    years = [int(entry["year"]) for entry in entries if entry.get("year")]
    recent = [year for year in years if year >= 2020]
    rigid_hits = [entry for entry in entries if _entry_matches(entry, ["particle", "颗粒", "sphere", "rigid", "solid", "小球"])]
    droplet_hits = [entry for entry in entries if _entry_matches(entry, ["drop", "droplet", "液滴", "oscillation", "coalescence"])]
    return {
        "source_count": len(entries),
        "latest_year": max(years) if years else None,
        "recent_2020_plus_count": len(recent),
        "rigid_particle_count": len(rigid_hits),
        "droplet_count": len(droplet_hits),
        "seed_reference_count": sum(1 for entry in entries if entry.get("origin") == "web_seed"),
        "recent_external_count": sum(1 for entry in entries if entry.get("origin") == "recent_external"),
        "library_files": sorted({entry.get("source_file") for entry in entries if entry.get("source_file")}),
    }


def build_zotero_context(digest: dict[str, Any]) -> dict[str, Any]:
    if not digest:
        return {"available": False}
    summary = summarize_zotero_digest(digest)
    high_interest = digest.get("high_interest", [])
    if not isinstance(high_interest, list):
        high_interest = []
    return {
        "available": summary.get("available", False),
        "generated_at": summary.get("generated_at"),
        "digest_path": summary.get("path"),
        "provider": digest.get("provider"),
        "summary": summary,
        "collections": digest.get("collections", {}),
        "high_interest_preview": high_interest[:12],
        "usage_boundary": digest.get("usage_boundary", {}),
        "integration_rule": "Zotero plugin performs library access/export. Eureka only organizes the digest for Quill and Franklin context; it does not read Zotero directly or change processing methods.",
    }


def build_research_digest(corpus: dict[str, Any]) -> dict[str, Any]:
    entries = corpus.get("entries", [])
    current_year = datetime.now().year
    recent_cutoff = current_year - 5
    recent_entries = [
        entry
        for entry in entries
        if entry.get("year") is not None and int(entry["year"]) >= recent_cutoff
    ]
    recent_entries.sort(key=lambda entry: (int(entry.get("year") or 0), entry.get("title") or ""), reverse=True)
    group = corpus.get("group_meetings", {})
    phase_candidates = group.get("phase_candidates", [])
    report_mode = _group_meeting_report_mode(group)
    focus_terms = [
        ("硬质小球-液膜/PB 相互作用", ["particle", "sphere", "颗粒", "小球", "rigid", "interface"]),
        ("液滴/包覆体低耗散输运", ["droplet", "drop", "液滴", "antibubble", "encapsulated"]),
        ("PB/泡沫网络输运与无量纲相图", ["Plateau", "foam", "PB", "imbibition", "Re", "We", "Ca", "Bo"]),
        ("染色/可视化验证与气膜判别", ["dye", "visualization", "fluorescence", "interferometry", "gas film", "air film", "staining", "染色", "干涉", "气膜"]),
        ("识别与数据处理方法", ["tracking", "image", "fit", "ROI", "phase"]),
    ]
    themes = []

    def ref_payload(item: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "title": item.get("title"),
            "year": item.get("year"),
            "doi": item.get("doi"),
            "link": item.get("link"),
            "keywords": item.get("keywords") or item.get("method") or item.get("summary") or "",
            "origin": item.get("origin"),
            "source": item.get("source_file") or item.get("origin"),
        }
        payload["figure_url"] = _figure_url_for_reference(payload)
        return payload

    for name, terms in focus_terms:
        matched = [entry for entry in recent_entries if _entry_matches(entry, terms)]
        themes.append(
            {
                "name": name,
                "count": len(matched),
                "references": [ref_payload(item) for item in matched[:5]],
            }
        )
    stack_highlights = sorted(
        [
            entry
            for entry in entries
            if entry.get("origin") == "library"
            and (
                _entry_matches(entry, ["antibubble", "反气泡", "Plateau", "PB", "液膜", "droplet", "液滴", "particle", "颗粒", "无量纲", "dye", "染色", "interferometry", "气膜"])
                or entry.get("summary")
            )
        ],
        key=lambda entry: (
            2 if entry.get("year") and int(entry["year"]) >= 2020 else 1 if entry.get("year") and int(entry["year"]) >= 2015 else 0,
            len(_text(entry.get("summary"))) + len(_text(entry.get("keywords"))),
        ),
        reverse=True,
    )
    pb_particle_refs = [
        ref_payload(entry)
        for entry in entries
        if _entry_matches(entry, ["Plateau", "PB", "foam", "particle", "sphere", "颗粒", "小球", "interface", "液膜"])
        and entry.get("origin") in {"pb_particle_focus", "web_seed", "recent_external", "library"}
    ]
    pb_particle_refs = sorted(
        pb_particle_refs,
        key=lambda item: (
            1 if item.get("origin") == "pb_particle_focus" else 0,
            int(item.get("year") or 0),
            item.get("title") or "",
        ),
        reverse=True,
    )
    return {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "recent_cutoff_year": recent_cutoff,
        "recent_count": len(recent_entries),
        "zotero_context": build_zotero_context(corpus.get("zotero", {})),
        "themes": themes,
        "recent_references": [ref_payload(item) for item in recent_entries[:14]],
        "stack_highlights": [ref_payload(item) for item in stack_highlights[:10]],
        "pb_particle_brief": {
            "title": "PB-颗粒相互作用：Eureka 新增独立观察线",
            "claim": "硬质小球进入 PB/液膜附近时，先按受限颗粒-可变形界面问题理解；是否存在气膜、润湿接触或液桥，需要由染色/干涉/多光源可视化独立验证。",
            "experiment_checks": [
                "染色法：让 PB/液膜相与外部液相产生可见灰度或颜色差，观察小球周围是否有连续液桥、包裹液层或排液尾迹。",
                "背光/斜光双模式：背光保留轮廓追踪，斜光或荧光只用于判别界面与气膜，不直接改 Sisyphus 的主追踪结果。",
                "事件窗口：把接触前、贴附/滑移中、脱困后分开标记，再交给 Franklin 判断是否值得进入相图。",
            ],
            "franklin_boundary": "Eureka 只能给 Franklin 增加复核提示和评分惩罚建议；染色法或气膜模型要进入处理 pipeline，必须由用户确认。",
            "references": pb_particle_refs[:8],
        },
        "optimization_backlog": [
            {
                "title": "R-t 焦点/投影修正",
                "status": "可行优化，暂不作为默认物理结论",
                "note": "用于解释小球半径漂移；后续需要用焦点位置、相机-物距和未修正结果共同校验。",
            },
            {
                "title": "液滴震荡频率置信度",
                "status": "可行优化，暂不改 Franklin",
                "note": "当前部分窗口只有约两次典型震荡，频率只能作为候选量；后续可加入采样率、有效周期数和边界效应惩罚。",
            },
            {
                "title": "染色法判别颗粒-PB 接触状态",
                "status": "建议实验验证",
                "note": "优先回答是否有气膜、液桥或直接润湿接触，再决定是否扩展处理 pipeline。",
            },
        ],
        "paper_figure_dir": str(PAPER_FIGURE_DIR),
        "group_meeting_summary": {
            "file_count": group.get("file_count", 0),
            "slide_count": group.get("slide_count", 0),
            "phase_candidates": phase_candidates,
        },
        "presentation_style": report_mode["style"],
        "key_conclusions": report_mode["key_conclusions"],
        "inspection_route": report_mode["inspection_route"],
        "report_evidence_slides": report_mode["evidence_slides"],
        "future_work": [
            {
                "title": "建立硬质小球-液膜/PB 交互相图",
                "steps": [
                    "把材料、R、|v|、|a|/g、是否穿膜/卡滞/反弹统一进相图数据表。",
                    "用 Eureka 的近年颗粒-界面文献限定解释范围，Franklin 只负责筛掉识别跳变和短窗口。",
                    "下一批实验优先扫小球半径与入射速度，补足 PS/PMMA/POM/PP 的边界点。",
                ],
            },
            {
                "title": "把液滴类与硬质颗粒类分开建模",
                "steps": [
                    "液滴保留频率/阻尼/体积等效半径；硬球只用轨迹、速度、加速度和半径识别稳定性。",
                    "事件型 Case 先拆 Vfr，再进入拟合，不用全局一段解释所有阶段。",
                ],
            },
            {
                "title": "从组会文件迁移相图资产",
                "steps": [
                    "优先检查 phase_candidates 中提到 Re/We/Ca/Bo/相图的幻灯片。",
                    "后续可把 PPT slide 截图或图中坐标手动/半自动导入相图页，和当前视频 Case 点互相链接。",
                ],
            },
            {
                "title": "长期 APP 接入路线",
                "steps": [
                    "PPT：用于同步组会图、相图草稿和阶段性汇报结构。",
                    "Adobe Illustrator：用于把可复核草图升级为论文级矢量图。",
                    "Phantom camera control：未来接入现场实验采集，实现实验-处理-看板同步。",
                    "这些集成暂列 backlog，必须逐项确认后再开发，不影响当前自动处理 loop。",
                ],
            },
        ],
    }


def _entry_text(entry: dict[str, Any]) -> str:
    return " ".join(_text(entry.get(key)) for key in ["title", "keywords", "method", "summary"]).lower()


def _entry_matches(entry: dict[str, Any], terms: list[str]) -> bool:
    text = _entry_text(entry)
    return any(term.lower() in text for term in terms)


def _score_entry(entry: dict[str, Any], metrics: dict[str, Any], is_rigid: bool) -> float:
    text = _entry_text(entry)
    common = ["plateau", "pb", "foam", "film", "液膜", "泡沫", "输运", "界面", "border"]
    rigid_terms = ["particle", "particles", "颗粒", "sphere", "solid", "rigid", "jamming", "dispersion", "小球", "刚体"]
    droplet_terms = ["drop", "droplet", "液滴", "oscillation", "coalescence", "imbibition", "反气泡", "震荡"]
    score = sum(1.0 for term in common if term in text)
    score += sum(1.5 for term in (rigid_terms if is_rigid else droplet_terms) if term in text)
    material = _text(metrics.get("material")).lower()
    if material and material in text:
        score += 0.7
    year = entry.get("year")
    if year:
        score += 3.0 if int(year) >= 2020 else 1.0 if int(year) >= 2015 else 0.0
    if "review" in text or "综述" in text:
        score += 1.8
    if entry.get("doi") or entry.get("link"):
        score += 0.3
    return score


def _top_literature(entries: list[dict[str, Any]], metrics: dict[str, Any], is_rigid: bool) -> list[dict[str, Any]]:
    ranked = sorted(entries, key=lambda entry: _score_entry(entry, metrics, is_rigid), reverse=True)
    out = []
    for entry in ranked[:5]:
        score = _score_entry(entry, metrics, is_rigid)
        if score <= 0:
            continue
        out.append(
            {
                "title": entry.get("title"),
                "year": entry.get("year"),
                "doi": entry.get("doi"),
                "link": entry.get("link"),
                "origin": entry.get("origin"),
                "source": entry.get("source_file") or entry.get("origin"),
                "keywords": entry.get("keywords") or "",
                "method": entry.get("method") or "",
                "summary": entry.get("summary") or "",
            }
        )
    return out


def build_eureka_case(case: dict[str, Any], corpus: dict[str, Any]) -> dict[str, Any]:
    metrics = case.get("metrics") or {}
    review = case.get("review") or {}
    experiment_type = _text(metrics.get("experiment_type")).lower()
    is_rigid = experiment_type in {"rigid_ball", "rigid", "solid_ball", "hard_sphere", "sphere"}
    material = _text(metrics.get("material")) or "-"
    citations = _top_literature(corpus.get("entries", []), metrics, is_rigid)
    flags = set(review.get("flags") or [])

    if is_rigid:
        phenomenon = (
            f"{material} 硬质小球更适合被看作受限颗粒在 PB/液膜邻域的输运，而不是液滴震荡体系；"
            "Eureka 会优先区分自由飞行、界面/弯月面导向滑移、卡滞/脱困和疑似误识别四类现象。"
        )
        directions = [
            "建立 R 与 PB/液膜有效通道宽度的受限比，寻找从随流运动到卡滞/穿膜失败的阈值。",
            "按轨迹形态分段：入射、接近液膜、接触/拖曳弯月面、反弹或停滞；不要只用全局二次拟合概括。",
            "把 |a|/g、速度衰减和半径/质心突变放在同一张质控图中，用来区分真实受力变化与识别跳变。",
            "小半径小球若半径随位置呈 U 形变化，应优先作为投影/焦平面畸变诊断，另行跟踪横纵轴 a/b。",
        ]
        franklin = [
            "Franklin 应继续强罚半径突变、质心突变和短有效窗口。",
            "存在左侧液体运动时，ROI 需要排除左边界和动态液膜尾迹，避免把液体前沿当成小球。",
            "主运动方向默认按 x 处理，除非有效窗口内 y 位移显著更大。",
        ]
    else:
        phenomenon = (
            "该 Case 更接近液滴/包覆体在 PB 或液膜中的低耗散输运与界面耦合问题；"
            "Eureka 会优先关注并合、膜排液、惯性-黏性分区和震荡衰减。"
        )
        directions = [
            "用 R、v、a 与频率/阻尼共同判断是否存在低耗散滑移或界面导向输运。",
            "把二次拟合加速度和震荡频率分开解释：前者描述整体输运，后者描述形变模式。",
            "若频率接近扫描边界或拟合窗口敏感，应扩大候选窗口而不是直接解释成物理频率。",
            "将液滴半径、膜厚和 PB 几何联系到 Re、We、Ca、Bo 等无量纲数，后续进入相图区。",
        ]
        franklin = [
            "Franklin 应优先检查频率窗口稳定性、半径体积等效稳定性和拟合窗口敏感性。",
            "若并合/穿膜前后动力学不同，应拆分 Vfr，避免把事件前后混为同一段拟合。",
        ]

    metric_focus = []
    for label, key, unit in [
        ("半径", "radius_mean_mm", "mm"),
        ("速度", "velocity_abs_mean_mm_s", "mm/s"),
        ("二次拟合加速度", "primary_quad_accel_mm_s2", "mm/s^2"),
        ("震荡频率", "freq_mean_hz", "Hz"),
        ("半径相对波动", "radius_rel_std_percent", "%"),
    ]:
        value = metrics.get(key)
        if value is not None:
            metric_focus.append(f"{label}: {value} {unit}")

    if "center_step_jump" in flags or "radius_step_jump" in flags:
        directions.insert(0, "本 Case 的首要任务不是解释物理机制，而是先复核视频中目标身份是否连续。")

    gaps = []
    corpus_summary = corpus.get("summary", {})
    if is_rigid and int(corpus_summary.get("rigid_particle_count") or 0) < 6:
        gaps.append("本地文献库中硬质颗粒/小球在 PB 或液膜中输运的条目偏少，建议 Eureka 后续补充 2020+ 综述和颗粒-泡沫排液文献。")
    if not citations:
        gaps.append("未能从 library 中匹配到足够相关文献；需要补 DOI、题名或关键词。")

    confidence = 55 + min(len(citations) * 7, 28) + (8 if not gaps else 0)
    return {
        "agent": "Eureka",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "stance": "independent_literature_based",
        "phenomenon_summary": phenomenon,
        "analysis_directions": directions[:4],
        "metric_focus": metric_focus[:5],
        "franklin_coordination": franklin,
        "literature_matches": citations,
        "literature_gaps": gaps,
        "confidence": min(confidence, 95),
    }


def build_franklin_training(corpus: dict[str, Any]) -> dict[str, Any]:
    summary = corpus.get("summary", {})
    return {
        "agent": "Eureka",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "library_plus_seed_literature_plus_zotero_digest",
        "mode": "auditable_qc_rules_only",
        "scope_guardrails": [
            "Eureka 不修改主处理算法、ROI 搜索代码、拟合公式或物理结论。",
            "Eureka 只允许给 Franklin 增加可审计的 QC 惩罚、复核提示和相图准备标记。",
            "Eureka 可以影响 Franklin 的评分、复核优先级和重跑建议，但不能自动改变主处理 pipeline。",
            "Zotero 文献只作为 Eureka/Quill 的证据背景；除非用户确认，不得把 Zotero 文献方法转化为处理参数或新 pipeline。",
            "任何处理参数、算法或代码层面的变更只能生成 pending_user_approval 建议，必须由用户明确点头后执行。",
            "每条规则必须声明 target、trigger、score_effect、evidence_scope；不在白名单中的文献联想不得进入评分。",
            "硬质小球规则只用于目标身份连续性、半径/质心突变、短窗口等数据质量判断，不用于替代你的刚体动力学模型。",
            "液滴规则只用于事件窗口拆分和频率边界提醒，不直接重写现有液滴加速度/频率算法。",
        ],
        "library_summary": summary,
        "rules": [
            {
                "id": "rigid_identity_continuity",
                "enabled": True,
                "risk_level": "low",
                "target": "rigid_ball",
                "trigger": "center_step_jump or radius_step_jump or short_valid_window",
                "action": "penalize_score_and_request_roi_rerun",
                "permission": "score_and_review_only",
                "score_effect": "subtract up to 28 for center jumps, up to 24 for radius jumps, plus 10 for short valid window",
                "evidence_scope": "general particle/film/PB literature only supports that object identity must be continuous before mechanism interpretation; it does not alter tracking equations.",
                "reason": "硬质颗粒在 PB/液膜附近的真实物理响应应与目标身份连续性分开；文献解释前先保证不是液体界面被误识别。",
            },
            {
                "id": "rigid_no_oscillation_frequency",
                "enabled": True,
                "risk_level": "low",
                "target": "rigid_ball",
                "trigger": "rigid_ball",
                "action": "ignore_frequency_score_and_prioritize_x_t_fit_radius_center_qc",
                "permission": "score_and_review_only",
                "score_effect": "no direct subtraction; removes frequency as a meaningful rigid-ball interpretation channel",
                "evidence_scope": "object-class separation: rigid particles are not droplet oscillators.",
                "reason": "硬质小球不是液滴震荡体，频率项不应驱动评分。",
            },
            {
                "id": "droplet_event_window_split",
                "enabled": True,
                "risk_level": "low",
                "target": "droplet",
                "trigger": "coalescence_or_prefusion_or_fit_window_sensitive",
                "action": "request_valid_frame_split",
                "permission": "score_and_review_only",
                "score_effect": "subtract 6 only when Franklin already flags fit_window_sensitive",
                "evidence_scope": "PB/droplet literature supports event-stage separation; it does not overwrite fitted acceleration.",
                "reason": "液滴/PB 输运常含并合、排液、惯性-黏性分区，事件前后不应混作一个拟合窗口。",
            },
            {
                "id": "dimensionless_phase_readiness",
                "enabled": True,
                "risk_level": "none",
                "target": "all",
                "trigger": "radius_velocity_accel_available",
                "action": "promote_to_phase_space",
                "permission": "metadata_only",
                "score_effect": "none",
                "evidence_scope": "metadata annotation only.",
                "reason": "Eureka 将 R、v、a 作为后续 Re/We/Bo/Ca 相图入口。",
            },
        ],
    }


def apply_eureka_training_to_review(metrics: dict[str, Any], review: dict[str, Any], corpus: dict[str, Any] | None = None) -> dict[str, Any]:
    trained = dict(review)
    flags = set(trained.get("flags") or [])
    experiment_type = _text(metrics.get("experiment_type")).lower()
    is_rigid = experiment_type in {"rigid_ball", "rigid", "solid_ball", "hard_sphere", "sphere"}
    notes: list[str] = []
    applied_rules: list[dict[str, Any]] = []
    penalty = 0.0

    center_outliers = float(metrics.get("center_step_outlier_count") or 0)
    radius_jump = metrics.get("radius_step_rel_max_percent")
    try:
        radius_jump_value = float(radius_jump)
    except (TypeError, ValueError):
        radius_jump_value = 0.0

    if is_rigid:
        trained["method"] = "rigid_ball_literature_trained"
        flags.add("eureka_rigid_particle_mode")
        notes.append("Eureka: 刚体 Case 不使用液滴震荡频率作为质量判断，优先检查目标身份、质心连续性、半径连续性和 x-t 运动。")
        if center_outliers > 0:
            delta = min(28.0, 10.0 + 6.0 * center_outliers)
            penalty += delta
            flags.add("eureka_identity_continuity_penalty")
            notes.append("Eureka: 质心跳变会优先视为目标身份不连续或 ROI 污染，需重跑 ROI/Vfr 后再解释物理机制。")
            applied_rules.append({"id": "rigid_identity_continuity", "score_delta": -round(delta, 1), "triggered_by": "center_step_outlier_count"})
        if radius_jump_value > 12.0:
            delta = min(24.0, radius_jump_value * 0.75)
            penalty += delta
            flags.add("eureka_radius_jump_penalty")
            notes.append("Eureka: 硬球半径突变更可能是投影/识别问题，Franklin 应压低评分并要求复核。")
            applied_rules.append({"id": "rigid_identity_continuity", "score_delta": -round(delta, 1), "triggered_by": "radius_step_rel_max_percent"})
        valid_range = metrics.get("valid_frame_range")
        if isinstance(valid_range, list) and len(valid_range) == 2:
            try:
                if float(valid_range[1]) - float(valid_range[0]) + 1 < 45:
                    penalty += 10.0
                    flags.add("eureka_short_window_penalty")
                    notes.append("Eureka: 有效窗口过短，难以支撑受限颗粒输运机制判断。")
                    applied_rules.append({"id": "rigid_identity_continuity", "score_delta": -10.0, "triggered_by": "valid_frame_range"})
            except (TypeError, ValueError):
                pass
    else:
        if "fit_window_sensitive" in flags:
            penalty += 6.0
            flags.add("eureka_event_window_split")
            notes.append("Eureka: 液滴/PB 输运应拆分并合或接触事件前后的 Vfr，避免事件混合拟合。")
            applied_rules.append({"id": "droplet_event_window_split", "score_delta": -6.0, "triggered_by": "fit_window_sensitive"})
        if "frequency_near_scan_boundary" in flags:
            notes.append("Eureka: 频率靠近扫描边界时只能作为候选现象，不能直接作为机制结论。")

    if penalty:
        before = float(trained.get("reviewer_score") or 0.0)
        trained["reviewer_score_before_eureka"] = round(before, 1)
        trained["eureka_score_adjustment"] = round(-penalty, 1)
        trained["reviewer_score"] = round(max(0.0, before - penalty), 1)
        if trained["reviewer_score"] < 50:
            trained["band"] = "low_confidence"
        elif trained["reviewer_score"] < 70:
            trained["band"] = "needs_review"
        elif trained["reviewer_score"] < 85:
            trained["band"] = "usable_review"

    trained["flags"] = sorted(flags)
    trained["eureka_training"] = build_franklin_training(corpus or {"summary": {}})
    trained["eureka_training_notes"] = notes
    trained["eureka_applied_rules"] = applied_rules
    return trained


def write_eureka_profile(corpus: dict[str, Any], case_count: int) -> None:
    EUREKA_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "agent": "Eureka",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "mission": "Watch case videos through generated monitor assets and connect observed phenomena to a local literature stack.",
        "independence_rule": "Do not use the user's subjective notes as evidence; use library entries, metrics, videos, and Franklin QC flags.",
        "authority_boundary": "Eureka may influence Franklin's scoring and review priorities only. Processing code, ROI rules, fitting rules, and pipeline parameters remain governed by the user's explicit approval.",
        "library_summary": corpus.get("summary", {}),
        "franklin_training": build_franklin_training(corpus),
        "case_count_seen": case_count,
        "refresh_policy": "Prefer 2020+ and review papers; use DOI/link fields when available; add web-searched seed references only as explicit web_seed entries.",
    }
    with EUREKA_PROFILE_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Eureka literature corpus summary.")
    parser.add_argument("--library", default=str(LIBRARY_DIR), help="Library folder containing xlsx/md/txt/csv literature stacks.")
    parser.add_argument("--output", default=str(WORKFLOW_DIR / "eureka_corpus.json"), help="Output JSON path.")
    args = parser.parse_args()
    corpus = load_literature_corpus(Path(args.library))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        json.dump(corpus, f, indent=2, ensure_ascii=False)
    write_eureka_profile(corpus, case_count=0)
    print(f"Wrote {output}")
    print(json.dumps(corpus["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
