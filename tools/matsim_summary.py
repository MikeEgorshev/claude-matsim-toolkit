#!/usr/bin/env python3
"""
matsim_summary.py — компактная сводка network.xml / plans.xml в JSON.

Стримит большие XML (в т.ч. .gz) через iterparse, чтобы не держать в памяти
файлы на сотни МБ. Возвращает агрегаты + предупреждения о типичных ошибках
(например freespeed > 50 м/с почти всегда означает значение в км/ч).

Использование:
    python matsim_summary.py --network path/to/network.xml[.gz]
    python matsim_summary.py --plans   path/to/plans.xml[.gz]
    python matsim_summary.py --network net.xml.gz --plans plans.xml.gz --pretty

Зависимости: только стандартная библиотека.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


def _open_maybe_gzip(path: Path):
    """Открыть файл прозрачно для .gz."""
    if path.suffix == ".gz":
        return gzip.open(path, "rb")
    return path.open("rb")


def _stat(values: list[float]) -> dict:
    if not values:
        return {"min": None, "max": None, "count": 0}
    return {"min": round(min(values), 2), "max": round(max(values), 2), "count": len(values)}


# Порог: freespeed в МАТSim в м/с. >50 м/с = 180 км/ч — почти всегда ошибка
# (значение случайно оставлено в км/ч). 50 м/с = 180 км/ч уже выше любого лимита РК.
SUSPICIOUS_FREESPEED_MS = 50.0


def summarize_network(path: Path) -> dict:
    nodes = 0
    freespeeds: list[float] = []
    capacities: list[float] = []
    road_types: Counter = Counter()
    suspicious = 0
    link_count = 0

    with _open_maybe_gzip(path) as f:
        for event, elem in ET.iterparse(f, events=("end",)):
            tag = elem.tag.split("}")[-1]  # снять namespace если есть
            if tag == "node":
                nodes += 1
                elem.clear()
            elif tag == "link":
                link_count += 1
                fs = elem.get("freespeed")
                if fs is not None:
                    try:
                        fsv = float(fs)
                        freespeeds.append(fsv)
                        if fsv > SUSPICIOUS_FREESPEED_MS:
                            suspicious += 1
                    except ValueError:
                        pass
                cap = elem.get("capacity")
                if cap is not None:
                    try:
                        capacities.append(float(cap))
                    except ValueError:
                        pass
                # тип дороги: либо атрибут type, либо attribute osm:way:highway
                rtype = elem.get("type")
                if rtype:
                    road_types[rtype] += 1
                elem.clear()

    warnings = []
    if suspicious:
        warnings.append(
            f"{suspicious} звеньев с freespeed > {SUSPICIOUS_FREESPEED_MS} м/с "
            f"(>{SUSPICIOUS_FREESPEED_MS * 3.6:.0f} км/ч) — вероятно значение в км/ч вместо м/с [правило N4]"
        )

    result = {
        "file": str(path),
        "nodes": nodes,
        "links": link_count,
        "freespeed_ms": _stat(freespeeds),
        "capacity_vph": _stat(capacities),
        "warnings": warnings,
    }
    if road_types:
        result["road_types"] = dict(road_types.most_common(15))
    return result


def summarize_plans(path: Path) -> dict:
    persons = 0
    activity_types: Counter = Counter()
    leg_modes: Counter = Counter()

    with _open_maybe_gzip(path) as f:
        for event, elem in ET.iterparse(f, events=("end",)):
            tag = elem.tag.split("}")[-1]
            if tag == "person":
                persons += 1
                elem.clear()
            elif tag == "activity" or tag == "act":
                t = elem.get("type")
                if t:
                    activity_types[t] += 1
            elif tag == "leg":
                m = elem.get("mode")
                if m:
                    leg_modes[m] += 1

    return {
        "file": str(path),
        "persons": persons,
        "activity_types": dict(activity_types.most_common(20)),
        "leg_modes": dict(leg_modes.most_common(20)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Компактная сводка MATSim network/plans в JSON.")
    parser.add_argument("--network", help="network.xml или .xml.gz")
    parser.add_argument("--plans", help="plans/population.xml или .xml.gz")
    parser.add_argument("--pretty", action="store_true", help="Читаемый отступ JSON")
    args = parser.parse_args(argv)

    if not args.network and not args.plans:
        parser.error("укажи --network и/или --plans")

    result: dict = {}
    if args.network:
        net_path = Path(args.network)
        if not net_path.exists():
            result["network_error"] = f"не найден: {net_path}"
        else:
            result["network"] = summarize_network(net_path)
    if args.plans:
        plans_path = Path(args.plans)
        if not plans_path.exists():
            result["plans_error"] = f"не найден: {plans_path}"
        else:
            result["plans"] = summarize_plans(plans_path)

    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
