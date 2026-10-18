#!/usr/bin/env python3
"""
Build the compact, web-ready 3D campus dataset from OpenStreetMap extracts.

Coordinate system (per campus):
    x : metres east of the campus base centre
    z : metres south of the campus base centre
    y : metres up (added by the renderer)

All geometry is derived from OSM (ODbL) and clipped to a rounded "model base".
Heights are estimates unless tagged in OSM or listed in MANUAL_HEIGHTS below.
"""
from __future__ import annotations

import json
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
    box,
    shape,
)
from shapely.ops import polygonize, unary_union

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "campuses.json"

EARTH_LON = 111_320.0
EARTH_LAT = 110_540.0


# ---------------------------------------------------------------------------
# Source facts and curated landmark metadata
# ---------------------------------------------------------------------------

CAMPUS_FACTS = {
    "handan": {
        "name": "邯郸校区",
        "en": "Handan Campus",
        "short": "邯郸",
        "address": "上海市杨浦区邯郸路 220 号",
        "founded": "1922 年迁入现址",
        "area_label": "约 1383 亩",
        "area_m2": 922_297,
        "accent": "#B08A4A",
        "tagline": "复旦主校区 · 百年学府的心脏",
        "description": (
            "邯郸校区是复旦大学的主校区，习惯上被称为“本部”。1922 年大学部迁入现址，"
            "此后校园向东、向南逐步扩展，形成今天东、南、北、中四个片区。光华楼、老校门、"
            "燕园与曦园共同构成最具辨识度的复旦校园意象。"
        ),
        "schools": "中国语言文学系、哲学学院、历史学系、经济学院、新闻学院、管理学院等",
        "stats_note": "校园面积依据学校公开资料；建筑体块按 OSM 轮廓整理",
    },
    "jiangwan": {
        "name": "江湾校区",
        "en": "Jiangwan Campus",
        "short": "江湾",
        "address": "上海市杨浦区淞沪路 2005 号",
        "founded": "2005 年启用",
        "area_label": "约 1600 亩",
        "area_m2": 1_066_667,
        "accent": "#3F7C6A",
        "tagline": "大草坪上的新校区 · 基础理科重镇",
        "description": (
            "江湾校区位于新江湾城西北部，是复旦面积最大的校区，2005 年百年校庆时一期建成。"
            "校园以开阔草坪、日湖与月湖、环形水系和低密度科研建筑群为特征，法学院、生命科学学院"
            "以及物理、化学、环境、材料等基础理科院系聚集于此。"
        ),
        "schools": "法学院、生命科学学院、物理学系、化学系、环境科学与工程系、材料科学系等",
        "stats_note": "校园面积依据学校公开资料；水系与绿地按 OSM 整理",
    },
    "fenglin": {
        "name": "枫林校区",
        "en": "Fenglin Campus",
        "short": "枫林",
        "address": "上海市徐汇区医学院路 138 号",
        "founded": "1937 年启用",
        "area_label": "约 288 亩",
        "area_m2": 192_000,
        "accent": "#9E2B36",
        "tagline": "东安路旁的医学圣殿 · 上医精神原乡",
        "description": (
            "枫林校区是原上海医科大学校址，俗称“医学院校区”，由东安路分为东苑与西苑。"
            "1936 年建成的东一号楼是上海市优秀历史建筑；福庆广场、同生广场与医科图书馆"
            "记录着“正谊明道”的上医传统。这里也是复旦大学上海医学院各医学院系的核心所在地。"
        ),
        "schools": "基础医学院、公共卫生学院、护理学院、临床医学院等",
        "stats_note": "校园面积依据学校公开资料；东苑、西苑边界按 OSM 与公开资料综合",
    },
}

# name -> curated data. `force` includes buildings just outside the OSM campus mask.
LANDMARKS = {
    "handan": {
        "光华楼": dict(priority=1, height=142, levels=30, type="landmark", special="guanghua",
                    desc="2005 年落成的复旦标志性建筑，双塔高 142 米，曾是中国大陆最高、全球前列的大学教学楼。"),
        "老校门": dict(priority=2, height=9, levels=2, type="historic", roof="hip", special="oldGate",
                    desc="复旦老校门是校园历史记忆的象征，也是毕业照最经典的取景地之一。"),
        "复旦大学理科图书馆": dict(priority=3, height=26, levels=5, type="library",
                    desc="理科图书馆，服务数学、物理、化学、生物等基础学科的教学与研究。"),
        "文科图书馆": dict(priority=4, height=30, levels=6, type="library",
                    desc="文科图书馆，馆藏人文社科文献，是邯郸校区重要的学习空间。"),
        "正大体育馆": dict(priority=5, height=24, type="sports",
                    desc="正大体育馆是邯郸校区的大型室内体育场馆，承办开学典礼、毕业典礼与各类赛事。"),
        "逸夫科技楼": dict(priority=6, height=45, levels=12, type="campus",
                    desc="逸夫科技楼位于校园东部，是科研与办公综合体。"),
        "恒隆物理楼": dict(priority=7, height=38, levels=10, type="campus",
                    desc="恒隆物理楼是物理学系的重要教学科研空间。"),
        "科学楼": dict(priority=8, height=45, levels=12, type="campus",
                    desc="科学楼位于校园北部，承担理科科研与实验功能。"),
        "计算中心": dict(priority=9, height=35, levels=9, type="campus",
                    desc="计算中心为全校提供计算、网络与信息化服务。"),
        "第一教学楼": dict(priority=10, height=24, levels=6, type="campus",
                    desc="第一教学楼是邯郸校区公共课与通识课程的重要教学场所。"),
        "新闻学院教学楼": dict(priority=11, height=28, levels=7, type="campus",
                    desc="新闻学院教学与实验空间，复旦新闻教育的重要载体。"),
        "史带楼": dict(priority=12, height=30, levels=8, type="campus",
                    desc="管理学院史带楼，承担管理教育与高层管理培训。"),
        "李达三楼": dict(priority=13, height=30, levels=8, type="campus",
                    desc="管理学院李达三楼，与史带楼共同构成管理学院建筑群。"),
        "子彬院": dict(priority=14, height=13, levels=3, type="historic", roof="hip",
                    desc="1925 年建成的子彬院，曾为心理学系所在地，是校园内重要的历史建筑。"),
        "北区食堂（科文时光中心）": dict(priority=15, height=14, levels=2, type="campus",
                    desc="北区食堂与科文时光中心，是北区学生生活的重要节点。"),
    },
    "jiangwan": {
        "李兆基图书馆": dict(priority=1, height=32, levels=8, type="library", special="libraryAtrium",
                    desc="江湾校区图书馆，2005 年启用，是江湾学术生活的核心空间。"),
        "廖凯原法学楼": dict(priority=2, height=26, levels=6, type="campus",
                    desc="法学院大楼，2005 年随江湾校区一期启用。"),
        "生命科学学院": dict(priority=3, height=32, levels=8, type="campus",
                    desc="生命科学学院科研楼，聚集生物学与生物医学研究团队。"),
        "物理科研楼": dict(priority=4, height=48, levels=12, type="campus",
                    desc="物理科研楼，江湾基础理科建筑群的重要组成部分。"),
        "化学楼": dict(priority=5, height=36, levels=8, type="campus",
                    desc="化学楼，承担化学系教学、实验与科研功能。"),
        "林太钰环境楼": dict(priority=6, height=30, levels=7, type="campus",
                    desc="环境科学与工程系所在楼宇，面向环境科学前沿研究。"),
        "先进材料实验室": dict(priority=7, height=30, levels=7, type="campus",
                    desc="先进材料实验室，聚焦材料科学交叉研究。"),
        "一号交叉学科楼": dict(priority=8, height=40, levels=10, type="campus",
                    desc="交叉学科楼，为跨院系科研合作提供空间。"),
        "二号交叉学科楼": dict(priority=9, height=40, levels=8, type="campus",
                    desc="二号交叉学科楼，江湾校区近年扩建的重要科研载体。"),
        "智华楼": dict(priority=10, height=24, levels=6, type="campus",
                    desc="智华楼是江湾校区的主要教学楼之一。"),
        "上海数学中心": dict(priority=11, height=32, levels=8, type="campus",
                    desc="上海数学中心，推动数学前沿研究与学术交流。"),
        "上海数学研究中心": dict(priority=11, height=32, levels=8, type="campus",
                    desc="上海数学中心，推动数学前沿研究与学术交流。"),
        "体育馆": dict(priority=12, height=22, type="sports",
                    desc="江湾校区室内体育馆，服务体育教学与师生日常运动。"),
        "食堂": dict(priority=13, height=15, levels=2, type="campus",
                    desc="江湾校区食堂，是校园生活区的重要节点。"),
        "江湾第二食堂": dict(priority=14, height=15, levels=2, type="campus",
                    desc="江湾第二食堂，服务不断扩展的校园生活区。"),
    },
    "fenglin": {
        "东1号楼": dict(priority=1, height=16, levels=4, type="historic", roof="hip",
                    desc="1936 年建成的国立上海医学院历史建筑，上海市优秀历史建筑，枫林校区的精神地标。"),
        "明道楼": dict(priority=2, height=55, levels=14, type="campus",
                    desc="明道楼位于东苑，是枫林校区重要的科研与行政楼宇。"),
        "治道楼": dict(priority=3, height=55, levels=14, type="campus",
                    desc="治道楼与明道楼相望，取名自“正谊明道”的上医院训。"),
        "复星楼（一号医学科研楼）": dict(priority=4, height=72, levels=18, type="campus",
                    desc="一号医学科研楼，2017 年揭牌，基础医学院与医学分子病毒学重点实验室等入驻。"),
        "康泉图书馆": dict(priority=5, height=80, levels=18, type="library",
                    desc="枫林校区医科图书馆，2017 年改扩建完成后成为医学学习与信息中心。"),
        "二号医学科研楼": dict(priority=6, height=85, levels=21, type="campus",
                    desc="二号医学科研楼，枫林校区改扩建的重要科研载体。"),
        "复旦大学公共卫生学院（西8号楼）": dict(priority=7, height=32, levels=8, type="campus",
                    desc="公共卫生学院所在楼宇，承担预防医学与公共卫生人才培养。"),
        "第一教学楼": dict(priority=8, height=24, levels=6, type="campus",
                    desc="枫林校区第一教学楼，医学基础教学的重要场所。"),
        "复旦大学枫林综合体育馆": dict(priority=9, height=25, type="sports",
                    desc="枫林校区综合体育馆，服务医学师生的体育教学与锻炼。"),
        "西7号楼": dict(priority=10, height=30, levels=7, type="campus",
                    desc="西苑教学科研楼之一，与西八号楼共同构成西苑建筑群。"),
        "实验动物科学部": dict(priority=11, height=18, levels=4, type="campus",
                    desc="实验动物科学部，为医学研究提供实验动物支撑。"),
        "门诊大楼": dict(priority=20, height=80, levels=22, type="hospital", force=True,
                    desc="复旦大学附属中山医院门诊大楼，与枫林校区东苑相邻。"),
    },
}

# Curated heights for major unnamed / poorly tagged campus buildings.
MANUAL_HEIGHTS = {
    "正大体育馆": 24, "北区体育馆": 20, "游泳馆": 14, "逸夫科技楼": 45,
    "恒隆物理楼": 38, "科学楼": 45, "计算中心": 35, "文科图书馆": 30,
    "复旦大学理科图书馆": 26, "卿云楼": 32, "第一教学楼": 24,
    "第二教学楼": 24, "第三教学楼": 24, "第四教学楼": 24,
    "第五教学楼": 24, "第六教学楼": 24, "新闻学院教学楼": 28,
    "新闻学院综合楼": 36, "新闻学院办公楼": 28, "史带楼": 30,
    "李达三楼": 30, "中华文明资源中心A楼": 30, "中华文明资源中心B楼": 30,
    "复旦招待所": 32, "北区食堂（科文时光中心）": 14, "旦苑餐厅（本部食堂）": 12,
    "复旦南区食堂": 12, "学生活动中心": 15, "校医院": 18,
    "马锦明楼": 30, "子彬院": 13, "老校门": 9, "博物馆（景莱堂）300#": 12,
    "博物馆（简公堂）200#": 12, "博物馆（相伯堂）100#": 12, "校友馆（奕住堂） 700#": 12,
    "档案馆": 20, "叶耀珍楼": 20, "抹云楼": 24, "逸夫楼": 20,
    "正大发展中心": 30, "美国研究中心": 20, "日本研究中心": 20,
    "微电子学院": 30, "遗传学楼": 25, "立人生物楼": 20,
    "袁成英楼": 25, "跃进楼": 20, "泛海楼": 28, "智库楼": 22,
    "寒冰馆": 12, "亚洲青年交流中心（青书馆）": 20, "东区艺术馆（杨泳曼楼）": 15,
    "演播厅": 15, "射击馆": 12, "艺教中心": 18, "文博系": 18,
    "材料一楼": 24, "材料二楼": 24, "电光源楼": 24,
    "现代物理研究所": 24, "兴业光学楼": 24, "帝斯曼合成方法及手性技术联合实验室": 20,
    "邮局": 10, "南区浴室": 10, "本部浴室": 10, "综合楼": 30,
    "外文楼": 24, "复旦招待所": 30, "留学生公寓": 40,
    "李兆基图书馆": 32, "廖凯原法学楼": 26, "生命科学学院": 32,
    "物理科研楼": 48, "化学楼": 36, "林太钰环境楼": 30,
    "先进材料实验室": 30, "一号交叉学科楼": 40, "二号交叉学科楼": 40,
    "智华楼": 24, "上海数学中心": 32, "上海数学研究中心": 32, "体育馆": 22, "食堂": 15,
    "江湾第二食堂": 15, "综合保障楼": 15, "A教学楼": 24,
    "复苑阁": 20, "复旦大学发育生物学研究所": 25,
    "东1号楼": 16, "明道楼": 55, "治道楼": 55, "复星楼（一号医学科研楼）": 72,
    "康泉图书馆": 80, "二号医学科研楼": 85, "东3号楼": 40,
    "东4号楼": 40, "东5号楼": 40, "东11号楼": 40, "法医/解剖": 30,
    "西7号楼": 30, "复旦大学公共卫生学院（西8号楼）": 32, "西13号楼": 30,
    "西16号楼（学生公寓东楼）": 60, "西17号楼（学生公寓西楼）": 60,
    "西20号楼": 60, "西21号楼": 60, "第一教学楼": 24, "第二教学楼": 24,
    "学生体育活动中心": 20, "复旦大学枫林综合体育馆": 25,
    "实验动物科学部": 18, "文化中心（西6号楼）": 20,
    "留学生公寓 民族餐厅": 40, "食堂 二号书院楼": 40,
    "门诊大楼": 80,
}

ROOF_OVERRIDES = {
    "老校门": "hip", "子彬院": "hip", "东1号楼": "hip",
}

TYPE_DEFAULT_HEIGHT = {
    "campus": 20, "dorm": 22, "library": 24, "hospital": 45,
    "commercial": 28, "residential": 18, "sports": 18, "historic": 13,
    "default": 12,
}
TYPE_DEFAULT_LEVELS = {
    "campus": 5, "dorm": 6, "library": 6, "hospital": 12,
    "commercial": 8, "residential": 5, "sports": 3, "historic": 3,
    "default": 3,
}

HOSPITAL_NAMES = {"复旦大学附属中山医院", "门诊大楼", "发热门诊"}

CAMPUS_BUILDING_NAME_HINTS = (
    "复旦", "上医", "医学院", "教学楼", "图书馆", "体育馆", "食堂", "宿舍",
    "科研", "实验", "学院", "书院", "中心", "校门", "礼堂", "办公楼",
)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def ring_from_way(elem: dict) -> list[tuple[float, float]]:
    return [(p["lon"], p["lat"]) for p in elem.get("geometry", [])]


def closed_polygon(ring: list[tuple[float, float]]) -> Polygon | None:
    if len(ring) < 3:
        return None
    if ring[0] != ring[-1]:
        ring = ring + [ring[0]]
    try:
        p = Polygon(ring)
        if not p.is_valid:
            p = p.buffer(0)
        if p.is_empty:
            return None
        if p.geom_type == "MultiPolygon":
            p = max(p.geoms, key=lambda g: g.area)
        return p if p.area > 1e-12 else None
    except Exception:
        return None


def largest_polygon(geom):
    if geom.is_empty:
        return None
    if geom.geom_type == "Polygon":
        return geom
    if geom.geom_type == "MultiPolygon":
        return max(geom.geoms, key=lambda g: g.area)
    if geom.geom_type == "GeometryCollection":
        polys = [g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        if not polys:
            return None
        return largest_polygon(max(polys, key=lambda g: g.area))
    return None


def parse_int(value, default=0):
    if value is None:
        return default
    m = re.search(r"\d+", str(value))
    return int(m.group()) if m else default


def parse_height(value):
    if value is None:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", str(value))
    return float(m.group(1)) if m else None


def classify_type(tags: dict, name: str) -> str:
    b = (tags.get("building") or "").lower()
    amenity = (tags.get("amenity") or "").lower()
    leisure = (tags.get("leisure") or "").lower()
    if tags.get("historic") in ("yes", "building") or name in ("老校门", "子彬院", "东1号楼"):
        return "historic"
    if amenity in ("library",) or b == "library":
        return "library"
    if amenity == "hospital" or b == "hospital" or name in HOSPITAL_NAMES or "医院" in name or "门诊" in name:
        return "hospital"
    if b in ("dormitory", "apartments") or "dormitory" in name.lower() or "宿舍" in name or "公寓" in name:
        return "dorm"
    if b in ("stadium", "sports_centre", "sports_hall") or leisure in ("stadium", "sports_centre", "sports_hall", "pitch", "track"):
        return "sports"
    if b in ("commercial", "retail", "hotel", "office") or amenity in ("hotel", "mall"):
        return "commercial"
    if b in ("residential", "house", "terrace"):
        return "residential"
    if b in ("university", "college", "school", "kindergarten") or amenity in ("university", "college", "school", "kindergarten"):
        return "campus"
    if b in ("yes", "church", "public", "civic", "government", "museum", "hospital"):
        return "campus" if ("复旦" in name or "大学" in name) else "default"
    return "default"


def clean_name(name: str) -> str:
    name = (name or "").strip().replace("\u3000", " ")
    name = re.sub(r"\s+", " ", name)
    m = re.fullmatch(r"(\d+)#", name)
    if m:
        return f"{m.group(1)}号楼"
    return name


def area_m2(geom: Polygon, lat0: float) -> float:
    # Fast local equal-area approximation (adequate at campus scale).
    return geom.area * EARTH_LON * math.cos(math.radians(lat0)) * EARTH_LAT


def corners(geom: Polygon) -> tuple[float, float, float, float]:
    return geom.bounds


# ---------------------------------------------------------------------------
# Load sources
# ---------------------------------------------------------------------------

def load_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def dedupe(elements):
    seen = set()
    out = []
    for e in elements:
        key = (e.get("type"), e.get("id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def build_masks():
    boundaries = load_json(RAW / "campus_boundaries.json")
    elements = {e["id"]: e for e in boundaries["elements"]}

    # Handan: a multipolygon relation made of many outer ways.
    rel = elements[3936746]
    lines = []
    for m in rel["members"]:
        if m.get("role") == "outer" and m.get("geometry"):
            lines.append(LineString([(p["lon"], p["lat"]) for p in m["geometry"]]))
    handan = unary_union(list(polygonize(lines)))

    jiangwan = closed_polygon(ring_from_way(elements[68998719]))

    fenglin_west = closed_polygon(ring_from_way(elements[294618101]))
    ctx = load_json(RAW / "fenglin_context.json")
    east_elem = next(e for e in ctx["elements"] if e.get("id") == 790296262)
    fenglin_east = closed_polygon(ring_from_way(east_elem))
    fenglin = unary_union([p for p in (fenglin_west, fenglin_east) if p is not None])

    return {
        "handan": handan,
        "jiangwan": jiangwan,
        "fenglin": fenglin,
    }


def campus_base(mask, margin_m: float, corner_m: float):
    minx, miny, maxx, maxy = mask.bounds
    lat0 = (miny + maxy) / 2
    mx = margin_m / (EARTH_LON * math.cos(math.radians(lat0)))
    my = margin_m / EARTH_LAT
    b = box(minx - mx, miny - my, maxx + mx, maxy + my)
    cr = corner_m / EARTH_LAT
    # Positive then negative buffer gives a clean rounded rectangle.
    b = b.buffer(cr, join_style=1).buffer(-cr, join_style=1)
    return b


# ---------------------------------------------------------------------------
# Main campus builder
# ---------------------------------------------------------------------------

def build_campus(cid: str, mask, elements, margin_m, corner_m, seed: int):
    facts = CAMPUS_FACTS[cid]
    base = campus_base(mask, margin_m, corner_m)
    lon0, lat0 = base.centroid.x, base.centroid.y
    coslat = math.cos(math.radians(lat0))

    def proj_xy(lon, lat):
        return ((lon - lon0) * EARTH_LON * coslat, (lat0 - lat) * EARTH_LAT)

    def proj_ring(ring):
        return [[round(x, 2), round(z, 2)] for x, z in (proj_xy(lon, lat) for lon, lat in ring)]

    def proj_line(line):
        return [[round(x, 2), round(z, 2)] for x, z in (proj_xy(lon, lat) for lon, lat in line.coords)]

    mask_local = mask
    base_local = base

    # -- base / campus surfaces ------------------------------------------------
    base_ring = proj_ring(list(base.exterior.coords))
    campus_parts = []
    if mask.geom_type == "Polygon":
        campus_parts = [mask]
    elif mask.geom_type == "MultiPolygon":
        campus_parts = list(mask.geoms)
    campus_rings = []
    for p in campus_parts:
        p = p.intersection(base)
        if p.is_empty:
            continue
        if p.geom_type == "Polygon":
            campus_rings.append(proj_ring(list(p.exterior.coords)))
        elif p.geom_type == "MultiPolygon":
            for q in p.geoms:
                campus_rings.append(proj_ring(list(q.exterior.coords)))

    # -- buildings -------------------------------------------------------------
    building_elements = []
    for e in elements:
        tags = e.get("tags", {})
        if "building" not in tags or "geometry" not in e:
            continue
        ring = ring_from_way(e)
        poly = closed_polygon(ring)
        if poly is None:
            continue
        building_elements.append((e, poly))

    # Landmarks can pull a building into the campus even if the OSM mask is tight.
    force_names = {n for n, d in LANDMARKS[cid].items() if d.get("force")}
    campus_buildings = []
    context_buildings = []

    # Guanghua is modelled as one twin-tower composition. OSM also contains
    # individual tower footprints inside the big outline; drop those duplicates.
    guanghua_poly = None
    if cid == "handan":
        for e, poly in building_elements:
            if clean_name(e.get("tags", {}).get("name", "")) == "光华楼":
                guanghua_poly = poly.buffer(0.00002)
                break

    for e, poly in building_elements:
        tags = e.get("tags", {})
        name = clean_name(tags.get("name") or tags.get("name:zh") or tags.get("official_name") or "")
        if not name:
            for key in ("name:en", "loc_name"):
                if tags.get(key):
                    name = clean_name(tags[key])
                    break
        area = area_m2(poly, lat0)
        if area < 12:
            continue
        centroid = poly.representative_point()
        if not base.contains(centroid) and not base.buffer(0.00001).contains(centroid):
            continue
        if guanghua_poly is not None and name != "光华楼" and guanghua_poly.contains(centroid):
            continue

        in_campus = centroid.within(mask.buffer(0.00012))  # ~13 m tolerance
        if name in force_names:
            in_campus = True
        # A few landmark buildings sit just outside a tight OSM campus outline.
        if cid == "fenglin" and name in LANDMARKS[cid]:
            in_campus = True

        typ = classify_type(tags, name)
        curated = LANDMARKS[cid].get(name, {})
        if curated.get("type"):
            typ = curated["type"]

        levels = parse_int(tags.get("building:levels"), 0)
        if curated.get("levels"):
            levels = curated["levels"]
        h = parse_height(tags.get("height"))
        if h is None:
            h = MANUAL_HEIGHTS.get(name)
        if curated.get("height"):
            h = curated["height"]
        if h is None:
            if levels:
                h = levels * 3.6 + 1.8
            else:
                h = TYPE_DEFAULT_HEIGHT.get(typ, 12)
                if typ == "campus" and area > 5000:
                    h += 6
                if typ == "dorm" and area > 1800:
                    h += 4
        h = max(6.0, min(float(h), 180.0))
        if levels == 0:
            levels = max(1, round((h - 1.5) / 3.6))

        if not in_campus:
            # Context buildings: mute, cap and simplify.
            h = min(h, 62.0)
            if len(name) and typ == "hospital":
                pass
            else:
                name = ""
            context_buildings.append(dict(
                id=e.get("id"),
                ring=proj_ring(list(poly.exterior.coords)),
                height=round(h, 1),
                type=typ,
                name=name,
                area=round(area, 0),
                levels=levels,
            ))
            continue

        # Campus buildings. Ensure name is present for major structures.
        if not name and area > 1400:
            name = "校园建筑"

        roof = ROOF_OVERRIDES.get(name, "flat")
        special = curated.get("special")
        local_ring = proj_ring(list(poly.exterior.coords))
        xs = [p[0] for p in local_ring]
        zs = [p[1] for p in local_ring]
        cx, cz = (min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2
        width, depth = max(xs) - min(xs), max(zs) - min(zs)

        b = dict(
            id=e.get("id"),
            name=name,
            en=clean_name(tags.get("name:en", "")),
            ring=local_ring,
            height=round(h, 1),
            levels=levels,
            type=typ,
            area=round(area, 0),
            roof=roof,
            center=[round(cx, 1), round(cz, 1)],
            width=round(width, 1),
            depth=round(depth, 1),
            landmark=bool(curated),
            priority=curated.get("priority", 99),
        )
        EN_NAMES = {
            "光华楼": "Guanghua Tower", "老校门": "The Old Gate",
            "李兆基图书馆": "Lee Shau Kee Library", "廖凯原法学楼": "Leo KoGuan Law Building",
            "康泉图书馆": "Kangquan Library", "复星楼（一号医学科研楼）": "Fosun Medical Research Building",
            "东1号楼": "Historic Building No.1 East", "明道楼": "Mingdao Building",
            "治道楼": "Zhidao Building", "复旦大学理科图书馆": "Science Library",
            "文科图书馆": "Humanities Library", "正大体育馆": "Zhengda Gymnasium",
            "子彬院": "Zibin Hall", "二号医学科研楼": "No.2 Medical Research Building",
            "复旦大学枫林综合体育馆": "Fenglin Sports Center",
        }
        if name in EN_NAMES:
            b["en"] = EN_NAMES[name]
        if curated.get("desc"):
            b["desc"] = curated["desc"]
        if special:
            b["special"] = special
            if special == "guanghua":
                # Two towers + podium, aligned with the long axis of the footprint.
                long_axis = "x" if width >= depth else "z"
                tower_size = round(min(42, max(24, (max(width, depth) - 30) / 2.5)), 1)
                offset = round(max(30, (max(width, depth) / 2) - tower_size * 0.72), 1)
                if long_axis == "x":
                    b["towers"] = [
                        [round(cx - offset, 1), round(cz, 1), tower_size],
                        [round(cx + offset, 1), round(cz, 1), tower_size],
                    ]
                else:
                    b["towers"] = [
                        [round(cx, 1), round(cz - offset, 1), tower_size],
                        [round(cx, 1), round(cz + offset, 1), tower_size],
                    ]
                b["podium_height"] = 25
                b["height"] = 142

        if cid == "fenglin" and name in LANDMARKS[cid] and name not in ("门诊大楼",):
            b["landmark"] = True
        campus_buildings.append(b)

    # Drop duplicate "yes"-type unnamed buildings that exactly overlap named ones.
    campus_buildings.sort(key=lambda b: (0 if b["name"] and b["name"] != "校园建筑" else 1, -b["area"]))

    # -- roads / paths ---------------------------------------------------------
    ROAD_WIDTH = {
        "motorway": 18, "trunk": 16, "primary": 14, "secondary": 12,
        "tertiary": 10, "residential": 8, "unclassified": 7, "living_street": 6,
        "service": 5, "pedestrian": 7, "footway": 3.0, "path": 2.6,
        "cycleway": 3.2, "steps": 2.4, "track": 3.0,
    }
    ROAD_MAJOR = {"motorway", "trunk", "primary", "secondary", "tertiary"}
    roads = []
    road_labels = []
    for e in elements:
        tags = e.get("tags", {})
        hw = tags.get("highway")
        if not hw or "geometry" not in e or tags.get("area") == "yes":
            continue
        kind = hw
        if hw in ("motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link"):
            kind = hw.replace("_link", "")
        if kind not in ROAD_WIDTH:
            continue
        line = LineString(ring_from_way(e))
        if line.is_empty or line.length <= 0:
            continue
        clipped = line.intersection(base)
        if clipped.is_empty:
            continue
        segments = []
        if clipped.geom_type == "LineString":
            segments = [clipped]
        elif clipped.geom_type == "MultiLineString":
            segments = list(clipped.geoms)
        for seg in segments:
            if seg.length * EARTH_LAT < 12:
                continue
            roads.append(dict(
                name=clean_name(tags.get("name", "")),
                class_=kind,
                width=ROAD_WIDTH[kind],
                line=proj_line(seg),
            ))

    # road labels for key named context roads
    by_name = defaultdict(float)
    for r in roads:
        if r["name"]:
            by_name[r["name"]] += max(1, len(r["line"]))
    key_names = ["邯郸路", "国定路", "淞沪路", "四平路", "政通路", "国权路",
                 "淞沪路", "国权北路", "殷行路", "国帆路", "日湖", "月湖",
                 "东安路", "医学院路", "肇嘉浜路", "斜土路", "枫林路"]
    used = set()
    for r in roads:
        n = r["name"]
        if n and n in key_names and n not in used and r["class_"] in ROAD_MAJOR and len(r["line"]) > 3:
            mid = r["line"][len(r["line"]) // 2]
            road_labels.append(dict(text=n, x=mid[0], z=mid[1], kind="road"))
            used.add(n)

    # -- land use --------------------------------------------------------------
    def add_polygon_feature(e, kind, subtype=""):
        p = closed_polygon(ring_from_way(e))
        if p is None:
            return
        p = p.intersection(base)
        if p.is_empty:
            return
        polys = [p] if p.geom_type == "Polygon" else list(p.geoms) if p.geom_type == "MultiPolygon" else []
        for q in polys:
            if q.area * EARTH_LON * coslat * EARTH_LAT < 10:
                continue
            areas.append(dict(kind=kind, subtype=subtype, ring=proj_ring(list(q.exterior.coords))))
        return p

    areas = []
    water_lines = []
    green_geoms = []
    water_geoms = []
    sports_geoms = []
    for_each = elements
    for e in for_each:
        tags = e.get("tags", {})
        if "geometry" not in e:
            continue
        p = None
        if tags.get("natural") == "water" or tags.get("waterway") in ("riverbank", "dock") or tags.get("landuse") in ("reservoir", "basin"):
            p = add_polygon_feature(e, "water")
            if p is not None:
                water_geoms.append(p)
        elif tags.get("leisure") in ("park", "garden", "nature_reserve", "common"):
            p = add_polygon_feature(e, "green")
            if p is not None:
                green_geoms.append(p)
        elif tags.get("landuse") in ("grass", "meadow", "forest", "village_green"):
            p = add_polygon_feature(e, "green")
            if p is not None:
                green_geoms.append(p)
        elif tags.get("natural") in ("wood", "scrub", "grassland", "heath"):
            p = add_polygon_feature(e, "green")
            if p is not None:
                green_geoms.append(p)
        elif tags.get("leisure") in ("track", "pitch", "stadium"):
            p = add_polygon_feature(e, "sports", tags.get("leisure"))
            if p is not None:
                sports_geoms.append(p)
        elif tags.get("landuse") == "recreation_ground":
            p = add_polygon_feature(e, "green")
            if p is not None:
                green_geoms.append(p)
        elif tags.get("amenity") == "parking" or tags.get("landuse") == "parking":
            add_polygon_feature(e, "parking")
        elif tags.get("place") == "square" or (tags.get("highway") == "pedestrian" and tags.get("area") == "yes"):
            add_polygon_feature(e, "plaza")

        if tags.get("waterway") in ("river", "stream", "canal", "ditch") and tags.get("area") != "yes":
            line = LineString(ring_from_way(e))
            clipped = line.intersection(base)
            if not clipped.is_empty:
                segs = [clipped] if clipped.geom_type == "LineString" else list(clipped.geoms) if clipped.geom_type == "MultiLineString" else []
                for seg in segs:
                    if seg.length > 8:
                        water_lines.append(dict(width=16 if tags.get("waterway") == "river" else 8, line=proj_line(seg)))

    # -- trees -----------------------------------------------------------------
    rng = random.Random(seed)
    road_geoms = []
    for r in roads:
        road_geoms.append(LineString(r["line"]))
    road_union = unary_union(road_geoms) if road_geoms else LineString()
    water_union = unary_union(water_geoms) if water_geoms else Polygon()
    green_union = unary_union(green_geoms) if green_geoms else Polygon()
    building_union = unary_union([closed_polygon(ring_from_way(e)) for e, _ in building_elements
                                  if closed_polygon(ring_from_way(e)) is not None])
    building_buf = building_union.buffer(3.0 / EARTH_LAT)
    road_buf = road_union.buffer(4.0 / EARTH_LAT)
    water_buf = water_union.buffer(2.0 / EARTH_LAT)

    # A helper working in lon/lat for accurate spacing.
    def point_ok(lon, lat, context=False):
        pt = Point(lon, lat)
        if not base.contains(pt):
            return False
        if not context and not mask.contains(pt):
            # allow campus green fringes but not the surrounding city
            if not green_union.contains(pt):
                return False
        if building_buf.contains(pt) or water_buf.contains(pt) or road_buf.contains(pt):
            return False
        return True

    trees = []
    # Dense planting in green areas.
    minx, miny, maxx, maxy = base.bounds
    step_lat = 10.8 / EARTH_LAT
    step_lon = 10.8 / (EARTH_LON * coslat)
    lat = miny
    while lat < maxy:
        lon = minx
        while lon < maxx:
            jx = lon + (rng.random() - 0.5) * step_lon * 0.9
            jz = lat + (rng.random() - 0.5) * step_lat * 0.9
            pt = Point(jx, jz)
            in_green = green_union.contains(pt)
            in_campus = mask.contains(pt)
            if in_green or (in_campus and rng.random() < 0.18):
                if point_ok(jx, jz, context=not in_campus):
                    x, z = proj_xy(jx, jz)
                    trees.append([round(x, 1), round(z, 1), round(rng.uniform(0.55, 0.92), 2), rng.randrange(3)])
            lon += step_lon
        lat += step_lat
        if len(trees) >= 4800:
            break

    # Street trees.
    for r in roads:
        if r["class_"] not in ("service", "residential", "tertiary", "secondary", "primary", "footway", "pedestrian"):
            continue
        if len(r["line"]) < 2:
            continue
        line = LineString([(x, z) for x, z in r["line"]])
        length = line.length
        if length < 18:
            continue
        step = 18.0
        offset = min(4.5, r["width"] / 2 + 1.2)
        for d in [step * i for i in range(1, int(length / step))]:
            p = line.interpolate(d)
            for sign in (-1, 1):
                # approximate normal in local metres
                p2 = line.interpolate(min(length, d + 1))
                dx, dz = p2.x - p.x, p2.y - p.y
                ln = math.hypot(dx, dz) or 1
                nx, nz = -dz / ln * offset * sign, dx / ln * offset * sign
                lon = lon0 + (p.x + nx) / (EARTH_LON * coslat)
                lat = lat0 - (p.y + nz) / EARTH_LAT
                if point_ok(lon, lat, context=not mask.contains(Point(lon, lat))):
                    if rng.random() < 0.72:
                        trees.append([round(p.x + nx, 1), round(p.y + nz, 1), round(rng.uniform(0.52, 0.86), 2), rng.randrange(3)])
        if len(trees) >= 5200:
            break

    # Deduplicate trees roughly (street trees may coincide with grid trees).
    seen = set()
    unique_trees = []
    for t in trees:
        key = (round(t[0] / 3), round(t[1] / 3))
        if key in seen:
            continue
        seen.add(key)
        unique_trees.append(t)
    tree_caps = {"handan": 2500, "jiangwan": 2200, "fenglin": 620}
    trees = unique_trees[:tree_caps[cid]]

    # -- labels ----------------------------------------------------------------
    labels = []
    used_names = set()
    for b in sorted([b for b in campus_buildings if b.get("landmark")], key=lambda b: b["priority"]):
        if b["priority"] > 16 or b["name"] in used_names:
            continue
        used_names.add(b["name"])
        labels.append(dict(
            text=b["name"], sub=f'{b["height"]:.0f} m · {b["levels"]}F',
            x=b["center"][0], z=b["center"][1], y=round(b["height"] + 6, 1),
            kind="building", priority=b["priority"],
        ))

    # Area labels (gardens, lakes, lawns) from OSM names.
    AREA_LABEL_NAMES = {
        "handan": {"燕园", "曦园", "光华楼前草坪", "相辉堂草坪", "国旗坪", "三角广场"},
        "jiangwan": {"日湖", "月湖"},
        "fenglin": {"颜福庆草坪"},
    }[cid]
    for e in elements:
        tags = e.get("tags", {})
        nm = clean_name(tags.get("name", ""))
        if nm in AREA_LABEL_NAMES and "geometry" in e:
            p = closed_polygon(ring_from_way(e))
            if p is None:
                continue
            c = p.representative_point()
            x, z = proj_xy(c.x, c.y)
            labels.append(dict(text=nm, sub="", x=round(x, 1), z=round(z, 1),
                               y=2.5, kind="area", priority=85))
            used_names.add(nm)

    # Add road labels to the overall label set but lower priority.
    for rl in road_labels[:6]:
        labels.append(dict(text=rl["text"], sub="", x=rl["x"], z=rl["z"], y=1.6, kind="road", priority=95))

    labels.sort(key=lambda l: l["priority"])

    # -- stats -----------------------------------------------------------------
    campus_area = area_m2(mask, lat0)
    green_area = area_m2(green_union.intersection(mask), lat0) if not green_union.is_empty else 0
    water_area = area_m2(water_union.intersection(mask), lat0) if not water_union.is_empty else 0
    max_h = max([b["height"] for b in campus_buildings] or [0])

    # -- compact output --------------------------------------------------------
    for b in campus_buildings:
        b.pop("width", None)
        b.pop("depth", None)
        if not b.get("en"):
            b.pop("en", None)

    data = dict(
        id=cid,
        name=facts["name"],
        en=facts["en"],
        short=facts["short"],
        address=facts["address"],
        founded=facts["founded"],
        areaLabel=facts["area_label"],
        areaOfficial=facts["area_m2"],
        accent=facts["accent"],
        tagline=facts["tagline"],
        description=facts["description"],
        schools=facts["schools"],
        statsNote=facts["stats_note"],
        center=[round(lon0, 6), round(lat0, 6)],
        extent=dict(
            width=round((base.bounds[2] - base.bounds[0]) * EARTH_LON * coslat, 0),
            depth=round((base.bounds[3] - base.bounds[1]) * EARTH_LAT, 0),
        ),
        base=base_ring,
        campus=campus_rings,
        buildings=campus_buildings,
        context=context_buildings,
        roads=roads,
        areas=areas,
        waterLines=water_lines,
        trees=trees,
        labels=labels,
        stats=dict(
            buildings=len(campus_buildings),
            campusArea=round(campus_area, 0),
            officialArea=facts["area_m2"],
            greenArea=round(green_area, 0),
            waterArea=round(water_area, 0),
            greenRatio=round(green_area / campus_area * 100, 1) if campus_area else 0,
            trees=len(trees),
            maxHeight=round(max_h, 0),
            contextBuildings=len(context_buildings),
        ),
    )
    return data


def main():
    masks = build_masks()
    sources = {
        "handan": [RAW / "handan_context.json"],
        "jiangwan": [RAW / "jiangwan.json"],
        "fenglin": [RAW / "fenglin_buildings.json", RAW / "fenglin_other.json"],
    }
    margins = {"handan": 110, "jiangwan": 100, "fenglin": 80}
    corners = {"handan": 36, "jiangwan": 36, "fenglin": 30}
    seeds = {"handan": 1905, "jiangwan": 2005, "fenglin": 1937}

    out = dict(
        meta=dict(
            title="复旦大学 · 一校三区",
            subtitle="邯郸 · 江湾 · 枫林",
            generated="2026-10-18",
            projection="Local tangent-plane approximation; metres east/south of campus base centre.",
            sources=[
                "OpenStreetMap contributors (ODbL 1.0) — building footprints, roads, water and green space",
                "复旦大学 / 复旦大学上海医学院公开资料 — 校区概况与历史信息",
                "维基百科（CC BY-SA 4.0） — 校区面积、历史与建筑背景",
            ],
            disclaimer="建筑高度、层数与立面为公开资料整理和示意性推定，不作为测绘或工程依据。",
        ),
        campuses=[],
    )
    for cid in ("handan", "jiangwan", "fenglin"):
        elements = []
        for path in sources[cid]:
            elements += load_json(path)["elements"]
        elements = dedupe(elements)
        print(f"[{cid}] {len(elements)} OSM elements, mask {masks[cid].geom_type}, "
              f"bounds {tuple(round(v, 5) for v in masks[cid].bounds)}")
        data = build_campus(cid, masks[cid], elements, margins[cid], corners[cid], seeds[cid])
        print(f"  -> {len(data['buildings'])} campus / {len(data['context'])} context buildings, "
              f"{len(data['roads'])} road segments, {len(data['trees'])} trees, "
              f"{len(data['labels'])} labels, {len(data['areas'])} areas")
        out["campuses"].append(data)

    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    size = OUT.stat().st_size
    print(f"Wrote {OUT} ({size / 1024 / 1024:.2f} MB)")


if __name__ == "__main__":
    main()
