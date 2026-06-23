from __future__ import annotations

import argparse
import html
import json
import math
import re
import textwrap
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont, ImageOps


BASE_DIR = Path(__file__).resolve().parent
DASHBOARD_DATA = BASE_DIR / "dashboard" / "dashboard_data.json"
FIGURE_DIR = BASE_DIR / "library" / "paper_figures"
MANIFEST_PATH = FIGURE_DIR / "_auto_manifest.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif")
TARGET_SIZE = (1000, 520)

KNOWN_REFERENCE_OVERRIDES = {
    "ultrasound-triggered drug release in vivo from antibubble-loaded macrophages": {
        "doi": "10.1016/j.jconrel.2024.12.007",
        "link": "https://www.sciencedirect.com/science/article/pii/S016836592400840X",
    },
    "drop impact on a foam-coated liquid surface: formation of antibubbles": {
        "doi": "10.1063/5.0253926",
        "link": "https://pubs.aip.org/aip/pof/article/37/2/023312/3336409/Drop-impact-on-a-foam-coated-liquid-surface",
    },
    "double emulsion templated monodisperse antibubbles via combined high-shear homogenization and t-junction microfluidics": {
        "doi": "10.1038/s41598-025-04009-0",
        "link": "https://www.nature.com/articles/s41598-025-04009-0",
    },
    "characterization of bubbles and antibubbles interfaces stabilized using pickering particles with different wetting properties": {
        "doi": "10.1002/ejlt.70048",
    },
    "polymeric antibubbles with strong ultrasound imaging capabilities": {
        "doi": "10.1039/D4CC03572K",
        "link": "https://pmc.ncbi.nlm.nih.gov/articles/PMC11427993/",
    },
    "influence of emulsification conditions on the preparation of nanoparticle-stabilized antibubbles: high-shear homogenization versus premix membrane emulsification": {
        "link": "https://www.sciencedirect.com/science/article/pii/S0927775724017990",
    },
}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def simple_slug(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"^https?://", "", value)
    value = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "_", value)
    return re.sub(r"_+", "_", value).strip("_")[:90] or "paper"


def figure_path_for(ref: dict[str, Any]) -> Path:
    key = simple_slug(_text(ref.get("doi")) or _text(ref.get("title")))
    return FIGURE_DIR / f"{key}.jpg"


def request_bytes(url: str, timeout: int = 14, limit: int | None = None) -> tuple[bytes, str, str]:
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        content_type = resp.getheader("Content-Type") or ""
        final_url = resp.geturl()
        if limit is None:
            data = resp.read()
        else:
            data = resp.read(limit)
    return data, content_type, final_url


def fetch_json(url: str) -> dict[str, Any] | None:
    try:
        raw, _, _ = request_bytes(url, timeout=12)
        return json.loads(raw.decode("utf-8", errors="ignore"))
    except Exception:
        return None


def title_similarity(a: str, b: str) -> float:
    a_norm = re.sub(r"\W+", " ", a.lower()).strip()
    b_norm = re.sub(r"\W+", " ", b.lower()).strip()
    if not a_norm or not b_norm:
        return 0.0
    return SequenceMatcher(None, a_norm, b_norm).ratio()


def enrich_reference(ref: dict[str, Any]) -> dict[str, Any]:
    out = dict(ref)
    title = _text(ref.get("title"))
    if not title:
        return out
    override = KNOWN_REFERENCE_OVERRIDES.get(title.lower())
    if override:
        for key, value in override.items():
            if value:
                out[key] = value

    if not out.get("doi"):
        crossref_url = f"https://api.crossref.org/works?query.title={quote(title)}&rows=4"
        payload = fetch_json(crossref_url)
        candidates = payload.get("message", {}).get("items", []) if payload else []
        best: tuple[float, dict[str, Any] | None] = (0.0, None)
        for item in candidates:
            item_title = " ".join(item.get("title") or [])
            score = title_similarity(title, item_title)
            if score > best[0]:
                best = (score, item)
        if best[1] and best[0] >= 0.62:
            item = best[1]
            out.setdefault("doi", item.get("DOI") or "")
            out.setdefault("link", item.get("URL") or "")
            if not out.get("year"):
                parts = (
                    item.get("published-print", {}).get("date-parts")
                    or item.get("published-online", {}).get("date-parts")
                    or item.get("issued", {}).get("date-parts")
                    or []
                )
                if parts and parts[0]:
                    out["year"] = parts[0][0]
            out["_crossref_score"] = round(best[0], 3)

    # Europe PMC often gives a PMCID for open biomedical papers.
    epmc_url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={quote(title)}&format=json&pageSize=3"
    payload = fetch_json(epmc_url)
    if payload:
        results = payload.get("resultList", {}).get("result", [])
        best: tuple[float, dict[str, Any] | None] = (0.0, None)
        for item in results:
            score = title_similarity(title, item.get("title", ""))
            if score > best[0]:
                best = (score, item)
        if best[1] and best[0] >= 0.68:
            item = best[1]
            out.setdefault("doi", item.get("doi") or "")
            out.setdefault("link", item.get("fullTextUrlList", {}).get("fullTextUrl", [{}])[0].get("url") if item.get("fullTextUrlList") else "")
            pmcid = item.get("pmcid")
            if pmcid:
                out["_pmc_url"] = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
            out["_epmc_score"] = round(best[0], 3)
    return out


def decode_attr(value: str) -> str:
    return html.unescape(value).strip().strip("'\"")


def extract_meta_images(html_text: str, base_url: str) -> list[tuple[str, str]]:
    images: list[tuple[str, str]] = []
    meta_pattern = re.compile(
        r"<meta[^>]+(?:property|name)=[\"'](?:og:image|og:image:url|twitter:image|citation_image|thumbnail)[\"'][^>]+content=[\"']([^\"']+)[\"'][^>]*>",
        re.I,
    )
    for match in meta_pattern.finditer(html_text):
        images.append((urljoin(base_url, decode_attr(match.group(1))), "meta image"))

    img_pattern = re.compile(r"<img\b([^>]+)>", re.I)
    attr_pattern = re.compile(r"([\w:-]+)\s*=\s*([\"'])(.*?)\2", re.I | re.S)
    for match in img_pattern.finditer(html_text):
        attrs = {name.lower(): decode_attr(value) for name, _, value in attr_pattern.findall(match.group(1))}
        src = attrs.get("data-src") or attrs.get("data-original") or attrs.get("src")
        if not src:
            continue
        note = " ".join(_text(attrs.get(key)) for key in ["alt", "title", "class", "id"])
        images.append((urljoin(base_url, src), note))
    link_pattern = re.compile(r"<a\b([^>]+)>(.*?)</a>", re.I | re.S)
    for match in link_pattern.finditer(html_text):
        attrs = {name.lower(): decode_attr(value) for name, _, value in attr_pattern.findall(match.group(1))}
        href = attrs.get("href")
        if not href:
            continue
        clean_href = href.split("?")[0].lower()
        if not clean_href.endswith(IMAGE_SUFFIXES):
            continue
        note = re.sub(r"<[^>]+>", " ", match.group(2))
        note = re.sub(r"\s+", " ", html.unescape(note)).strip()
        images.append((urljoin(base_url, href), note or "linked figure image"))
    return images


def sciencedirect_candidates(url: str) -> list[tuple[str, str]]:
    match = re.search(r"/pii/(S[0-9A-Z]+)", url, flags=re.I)
    if not match:
        return []
    pii = match.group(1)
    stems = [
        "ga1_lrg",
        "fx1_lrg",
        "gr1_lrg",
        "f1_lrg",
        "f2_lrg",
        "f3_lrg",
    ]
    return [(f"https://ars.els-cdn.com/content/image/1-s2.0-{pii}-{stem}.jpg", f"ScienceDirect {stem}") for stem in stems]


def source_urls(ref: dict[str, Any]) -> list[str]:
    urls = []
    if ref.get("_pmc_url"):
        urls.append(ref["_pmc_url"])
    if ref.get("doi"):
        urls.append(f"https://doi.org/{ref['doi']}")
    if ref.get("link"):
        urls.append(ref["link"])
    if ref.get("doi"):
        doi = ref["doi"]
        urls.extend(
            [
                f"https://pubs.acs.org/doi/{doi}",
                f"https://www.cambridge.org/core/search?filters%5BauthorTerms%5D=&q={quote(doi)}",
            ]
        )
    seen = set()
    out = []
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def score_image_candidate(url: str, note: str) -> float:
    text = f"{url} {note}".lower()
    score = 0.0
    positives = [
        "graphical",
        "figure",
        "fig",
        "scheme",
        "fx",
        "ga1",
        "gr1",
        "content/image",
        "article-image",
        "cms",
        "medium",
        "large",
        "lrg",
        "_f",
        "fig1",
        "fig2",
        "fig3",
        "setup",
        "apparatus",
        "experiment",
        "image_figure",
        "media.springernature",
    ]
    negatives = [
        "logo",
        "icon",
        "avatar",
        "cover",
        "journal-cover",
        "sprite",
        "facebook",
        "twitter",
        "placeholder",
        "transparent",
        "blank",
        "pmc-card-share",
        "card-share",
        "cms/images",
        "pubmed central",
        "national library of medicine",
        "nlm",
    ]
    for item in positives:
        if item in text:
            score += 2.0
    for item in negatives:
        if item in text:
            score -= 4.0
    if any(url.lower().split("?")[0].endswith(suffix) for suffix in IMAGE_SUFFIXES):
        score += 1.0
    if "antibubble" in text or "drop" in text or "particle" in text or "bubble" in text:
        score += 0.8
    if re.search(r"fig(?:ure)?\s*[1-4]\b", text):
        score += 2.5
    return score


def image_candidates(ref: dict[str, Any]) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    for url in source_urls(ref):
        candidates.extend(sciencedirect_candidates(url))
        try:
            raw, content_type, final_url = request_bytes(url, timeout=15, limit=3_000_000)
        except Exception:
            continue
        if "image/" in content_type:
            candidates.append((final_url, "landing image"))
            continue
        text = raw.decode("utf-8", errors="ignore")
        candidates.extend(extract_meta_images(text, final_url))
        candidates.extend(sciencedirect_candidates(final_url))

    ranked = sorted(
        [(score_image_candidate(url, note), url, note) for url, note in candidates],
        key=lambda item: item[0],
        reverse=True,
    )
    seen = set()
    out = []
    for score, url, note in ranked:
        if score < 1.0:
            continue
        clean = url.split("#")[0]
        if clean in seen or clean.startswith("data:"):
            continue
        seen.add(clean)
        out.append((clean, note))
    return out[:18]


def normalize_image(src: Image.Image) -> Image.Image:
    src = ImageOps.exif_transpose(src)
    if src.mode not in {"RGB", "RGBA"}:
        src = src.convert("RGB")
    if src.mode == "RGBA":
        bg = Image.new("RGB", src.size, "white")
        bg.paste(src, mask=src.getchannel("A"))
        src = bg
    src.thumbnail((TARGET_SIZE[0], TARGET_SIZE[1]), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", TARGET_SIZE, "#f7fafc")
    x = (TARGET_SIZE[0] - src.width) // 2
    y = (TARGET_SIZE[1] - src.height) // 2
    canvas.paste(src, (x, y))
    return canvas


def try_download_image(url: str, target: Path) -> bool:
    try:
        raw, content_type, _ = request_bytes(url, timeout=18, limit=8_000_000)
        if len(raw) < 5000 and "svg" not in content_type:
            return False
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(raw)
        with Image.open(tmp) as img:
            if img.width < 220 or img.height < 120:
                tmp.unlink(missing_ok=True)
                return False
            normalized = normalize_image(img)
            normalized.save(target, "JPEG", quality=88, optimize=True)
        tmp.unlink(missing_ok=True)
        return True
    except Exception:
        try:
            target.with_suffix(".tmp").unlink(missing_ok=True)
        except Exception:
            pass
        return False


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def draw_wrapped(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, width: int, fill: str, fnt: ImageFont.ImageFont, line_gap: int = 4, max_lines: int = 4) -> int:
    x, y = xy
    lines: list[str] = []
    for para in text.splitlines():
        if not para.strip():
            continue
        current = ""
        tokens = re.split(r"(\s+)", para)
        expanded_tokens: list[str] = []
        for token in tokens:
            if draw.textlength(token, font=fnt) > width:
                expanded_tokens.extend(list(token))
            else:
                expanded_tokens.append(token)
        for word in expanded_tokens:
            candidate = current + word
            if draw.textlength(candidate, font=fnt) <= width:
                current = candidate
            else:
                if current.strip():
                    lines.append(current.strip())
                current = word.strip()
        if current.strip():
            lines.append(current.strip())
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".。") + "..."
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=fill)
        bbox = draw.textbbox((x, y), line, font=fnt)
        y += bbox[3] - bbox[1] + line_gap
    return y


def draw_metadata_panel(draw: ImageDraw.ImageDraw, ref: dict[str, Any]) -> None:
    x0, y0, x1, y1 = 600, 78, 920, 414
    draw.rounded_rectangle((x0, y0, x1, y1), radius=18, fill="#f8fafc", outline="#d7e1ef", width=2)
    draw.text((x0 + 28, y0 + 28), "NO OPEN FIGURE", font=font(19, True), fill="#2456d6")
    draw.text((x0 + 28, y0 + 62), "metadata fallback", font=font(15), fill="#667085")
    tags = []
    text = " ".join(_text(ref.get(key)) for key in ["title", "keywords", "summary"]).lower()
    for label, terms in [
        ("setup", ["impact", "microfluidic", "column", "experiment"]),
        ("interface", ["interface", "film", "foam", "plateau"]),
        ("particle", ["particle", "pickering", "sphere"]),
        ("ultrasound", ["ultrasound", "drug"]),
        ("transport", ["transport", "release", "lifetime"]),
    ]:
        if any(term in text for term in terms):
            tags.append(label)
    tags = tags[:5] or ["antibubble", "recent"]
    y = y0 + 116
    for tag in tags:
        draw.rounded_rectangle((x0 + 28, y, x0 + 175, y + 34), radius=17, fill="#e9efff")
        draw.text((x0 + 44, y + 8), tag, font=font(15, True), fill="#2456d6")
        y += 44
    draw.line((x0 + 28, y1 - 68, x1 - 28, y1 - 68), fill="#d7e1ef", width=2)
    draw.text((x0 + 28, y1 - 48), "replaceable by fetcher", font=font(14), fill="#667085")


def make_summary_card(ref: dict[str, Any], target: Path) -> None:
    img = Image.new("RGB", TARGET_SIZE, "#ffffff")
    draw = ImageDraw.Draw(img)
    for y in range(TARGET_SIZE[1]):
        ratio = y / TARGET_SIZE[1]
        r = int(239 * (1 - ratio) + 229 * ratio)
        g = int(246 * (1 - ratio) + 247 * ratio)
        b = int(255 * (1 - ratio) + 240 * ratio)
        draw.line((0, y, TARGET_SIZE[0], y), fill=(r, g, b))
    draw.rounded_rectangle((28, 28, 970, 492), radius=18, fill="#ffffff", outline="#d7e1ef", width=2)
    draw.text((52, 54), str(ref.get("year") or "paper"), font=font(24, True), fill="#2456d6")
    draw.text((52, 92), "LITERATURE CARD", font=font(16, True), fill="#10934f")
    y = draw_wrapped(draw, (52, 130), _text(ref.get("title")), 520, "#111827", font(28, True), line_gap=7, max_lines=4)
    note = _text(ref.get("keywords") or ref.get("summary") or "Key result visual generated from paper metadata.")
    draw_wrapped(draw, (52, min(y + 18, 330)), note, 520, "#475467", font(18), max_lines=3)
    source = _text(ref.get("doi") or ref.get("link") or ref.get("source") or ref.get("origin") or "source pending")
    draw.text((52, 450), f"source: {source[:92]}", font=font(15), fill="#667085")
    draw_metadata_panel(draw, ref)
    img.save(target, "JPEG", quality=88, optimize=True)


def load_manifest() -> dict[str, Any]:
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"version": 1, "items": []}


def save_manifest(items: list[dict[str, Any]]) -> None:
    payload = {
        "version": 1,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "items": items,
    }
    MANIFEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_references(limit: int) -> list[dict[str, Any]]:
    payload = json.loads(DASHBOARD_DATA.read_text(encoding="utf-8"))
    refs = payload.get("eureka_research", {}).get("recent_references", [])
    return refs[:limit]


def fill_figures(limit: int = 14, force: bool = False, offline: bool = False) -> list[dict[str, Any]]:
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    refs = load_references(limit)
    old_items = {item.get("title"): item for item in load_manifest().get("items", [])}
    results: list[dict[str, Any]] = []
    for index, original_ref in enumerate(refs, start=1):
        ref = dict(original_ref) if offline else enrich_reference(original_ref)
        target = figure_path_for(ref)
        result = {
            "index": index,
            "title": ref.get("title"),
            "year": ref.get("year"),
            "doi": ref.get("doi"),
            "link": ref.get("link"),
            "path": str(target),
            "status": "skipped_existing" if target.exists() and not force else "pending",
            "kind": old_items.get(ref.get("title"), {}).get("kind") if target.exists() and not force else "",
            "source_url": old_items.get(ref.get("title"), {}).get("source_url") if target.exists() and not force else "",
        }
        if target.exists() and not force:
            results.append(result)
            print(f"[{index:02d}] keep {target.name}")
            continue

        downloaded = False
        tried = []
        if not offline:
            for url, note in image_candidates(ref):
                tried.append(url)
                if try_download_image(url, target):
                    result.update({"status": "downloaded", "kind": "paper_image", "source_url": url, "source_note": note})
                    downloaded = True
                    print(f"[{index:02d}] downloaded {target.name} <- {url}")
                    break
        if not downloaded:
            make_summary_card(ref, target)
            result.update({"status": "generated", "kind": "auto_summary", "source_url": ref.get("link") or ref.get("doi") or "", "tried": tried[:8]})
            print(f"[{index:02d}] generated summary {target.name}")
        results.append(result)
    save_manifest(results)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Auto-fill paper result figures for the literature radar.")
    parser.add_argument("--limit", type=int, default=14, help="Number of recent references to fill.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing auto figures.")
    parser.add_argument("--offline", action="store_true", help="Skip network and generate metadata cards for missing figures.")
    args = parser.parse_args()
    fill_figures(limit=args.limit, force=args.force, offline=args.offline)


if __name__ == "__main__":
    main()
