#!/usr/bin/env python3
"""
matsim_modify.py — типизированное изменение MATSim network.xml с валидацией ДО записи.

Единственный инструмент, который МЕНЯЕТ модель, поэтому он максимально осторожен:
  * валидирует все параметры до записи (capacity > 0, freespeed в м/с, link существует);
  * пишет в КОПИЮ (--output), оригинал не трогает (перезапись только с --force);
  * сохраняет DOCTYPE (MATSim ругается без него);
  * возвращает JSON-отчёт: что изменено, старое → новое, предупреждения.

Операции (можно комбинировать в одном вызове, применяются к --links):
    --set-capacity VALUE        пропускная способность, авт/ч (> 0)
    --set-freespeed VALUE       скорость свободного потока, М/С (> 0)
    --set-freespeed-kmh VALUE   то же, но в КМ/Ч (инструмент сам делит на 3.6)
    --set-lanes VALUE           число полос → атрибут permlanes (>= 1)
    --remove-modes MODE[,..]    убрать режимы из modes (по умолч. для --close-link: car)
    --close-link                закрыть для авто (= --remove-modes car), link остаётся в графе

Примеры:
    # Закрыть мост для авто, записать в копию
    python matsim_modify.py --network net.xml --output net_bridge_closed.xml \\
        --links 456 --close-link

    # Поднять capacity дублёров и проверить что бы изменилось (без записи)
    python matsim_modify.py --network net.xml --output net2.xml \\
        --links 12,13,14 --set-capacity 1200 --dry-run

Зависимости: только стандартная библиотека.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SUSPICIOUS_FREESPEED_MS = 50.0  # > 180 км/ч — почти всегда значение случайно в км/ч
DOCTYPE_RE = re.compile(rb"<!DOCTYPE[^>]*>")


def _read_text(path: Path) -> str:
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as f:
            return f.read().decode("utf-8")
    return path.read_text(encoding="utf-8")


def _extract_doctype(raw: str) -> str | None:
    m = DOCTYPE_RE.search(raw.encode("utf-8"))
    return m.group(0).decode("utf-8") if m else None


def _write_network(path: Path, root: ET.Element, doctype: str | None) -> None:
    body = ET.tostring(root, encoding="unicode")
    parts = ['<?xml version="1.0" encoding="UTF-8"?>']
    if doctype:
        parts.append(doctype)
    parts.append(body)
    content = "\n".join(parts) + "\n"
    if path.suffix == ".gz":
        with gzip.open(path, "wb") as f:
            f.write(content.encode("utf-8"))
    else:
        path.write_text(content, encoding="utf-8")


def validate_ops(args: argparse.Namespace) -> list[str]:
    """Проверить параметры операций ДО любого касания файла."""
    errors: list[str] = []
    if args.set_capacity is not None and args.set_capacity <= 0:
        errors.append(f"capacity должна быть > 0, передано {args.set_capacity}")
    if args.set_freespeed is not None and args.set_freespeed <= 0:
        errors.append(f"freespeed должна быть > 0, передано {args.set_freespeed}")
    if args.set_freespeed_kmh is not None and args.set_freespeed_kmh <= 0:
        errors.append(f"freespeed (км/ч) должна быть > 0, передано {args.set_freespeed_kmh}")
    if args.set_freespeed is not None and args.set_freespeed_kmh is not None:
        errors.append("укажи либо --set-freespeed (м/с), либо --set-freespeed-kmh, не оба")
    if args.set_lanes is not None and args.set_lanes < 1:
        errors.append(f"число полос должно быть >= 1, передано {args.set_lanes}")
    return errors


def collect_changes(args: argparse.Namespace) -> tuple[dict[str, str], list[str]]:
    """Собрать {attr: new_value} и список режимов на удаление. Вернуть (attr_changes, modes_to_remove)."""
    attr_changes: dict[str, str] = {}
    warnings: list[str] = []

    if args.set_capacity is not None:
        attr_changes["capacity"] = str(args.set_capacity)
    if args.set_freespeed is not None:
        if args.set_freespeed > SUSPICIOUS_FREESPEED_MS:
            warnings.append(
                f"freespeed {args.set_freespeed} м/с (> {SUSPICIOUS_FREESPEED_MS}) — "
                f"это {args.set_freespeed * 3.6:.0f} км/ч. Точно в м/с, не в км/ч? [правило N4]"
            )
        attr_changes["freespeed"] = str(args.set_freespeed)
    if args.set_freespeed_kmh is not None:
        ms = round(args.set_freespeed_kmh / 3.6, 4)
        attr_changes["freespeed"] = str(ms)
    if args.set_lanes is not None:
        attr_changes["permlanes"] = str(float(args.set_lanes))

    modes_to_remove: list[str] = []
    if args.close_link:
        modes_to_remove.append("car")
    if args.remove_modes:
        modes_to_remove += [m.strip() for m in args.remove_modes.split(",") if m.strip()]

    return attr_changes, list(dict.fromkeys(modes_to_remove))  # dedupe, keep order, + warnings via closure


def apply_modifications(args: argparse.Namespace) -> dict:
    net_in = Path(args.network)
    result: dict = {
        "status": "ok",
        "network_in": str(net_in),
        "network_out": args.output,
        "operations": [],
        "changed": [],
        "warnings": [],
        "errors": [],
    }

    # 0. Валидация параметров
    param_errors = validate_ops(args)
    if param_errors:
        result["status"] = "invalid"
        result["errors"] = param_errors
        return result

    attr_changes, modes_to_remove = collect_changes(args)
    if not attr_changes and not modes_to_remove:
        result["status"] = "noop"
        result["errors"].append("не задана ни одна операция изменения")
        return result

    # freespeed-варнинг (повторно собираем, т.к. collect_changes варнинги не вернул отдельно)
    if args.set_freespeed is not None and args.set_freespeed > SUSPICIOUS_FREESPEED_MS:
        result["warnings"].append(
            f"freespeed {args.set_freespeed} м/с = {args.set_freespeed * 3.6:.0f} км/ч — "
            f"проверь что значение в м/с, не км/ч [правило N4]"
        )

    result["operations"] = (
        [f"{k}={v}" for k, v in attr_changes.items()]
        + ([f"remove-modes={','.join(modes_to_remove)}"] if modes_to_remove else [])
    )

    if not net_in.exists():
        result["status"] = "error"
        result["errors"].append(f"сеть не найдена: {net_in}")
        return result

    # Цели
    target_ids = {x.strip() for x in args.links.split(",") if x.strip()}
    if not target_ids:
        result["status"] = "error"
        result["errors"].append("не указаны --links")
        return result

    # Защита оригинала
    out_path = Path(args.output)
    if out_path.resolve() == net_in.resolve() and not args.force:
        result["status"] = "error"
        result["errors"].append(
            "output совпадает с входной сетью. Укажи другой --output или --force для перезаписи."
        )
        return result

    # Разбор
    raw = _read_text(net_in)
    doctype = _extract_doctype(raw)
    root = ET.fromstring(raw)

    # Индекс существующих link id
    links_by_id = {}
    for link in root.iter("link"):
        lid = link.get("id")
        if lid is not None:
            links_by_id[lid] = link

    missing = sorted(target_ids - set(links_by_id))
    if missing:
        result["status"] = "error"
        result["errors"].append(f"не найдены link id в сети: {', '.join(missing)}")
        return result

    # Применение
    for lid in sorted(target_ids):
        link = links_by_id[lid]
        change_record: dict = {"link_id": lid, "fields": {}}

        for attr, new_val in attr_changes.items():
            old_val = link.get(attr)
            link.set(attr, new_val)
            change_record["fields"][attr] = {"old": old_val, "new": new_val}

        if modes_to_remove:
            old_modes = link.get("modes", "")
            current = [m.strip() for m in old_modes.split(",") if m.strip()]
            new_modes = [m for m in current if m not in modes_to_remove]
            link.set("modes", ",".join(new_modes))
            change_record["fields"]["modes"] = {"old": old_modes, "new": ",".join(new_modes)}
            if not new_modes:
                result["warnings"].append(
                    f"link {lid}: после удаления режимов modes пуст — агенты не смогут "
                    f"использовать это звено вообще (возможны проблемы маршрутизации)"
                )

        result["changed"].append(change_record)

    # Запись (если не dry-run)
    if args.dry_run:
        result["status"] = "dry_run"
        return result

    out_path.parent.mkdir(parents=True, exist_ok=True)
    _write_network(out_path, root, doctype)
    result["status"] = "written"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Изменить MATSim network.xml с валидацией.")
    parser.add_argument("--network", required=True, help="Входной network.xml[.gz]")
    parser.add_argument("--output", required=True, help="Выходной network.xml[.gz] (копия)")
    parser.add_argument("--links", required=True, help="ID звеньев через запятую: 456 или 12,13,14")
    parser.add_argument("--set-capacity", type=float, help="Новая capacity, авт/ч (> 0)")
    parser.add_argument("--set-freespeed", type=float, help="Новая freespeed, М/С (> 0)")
    parser.add_argument("--set-freespeed-kmh", type=float, help="Новая freespeed в КМ/Ч (÷3.6)")
    parser.add_argument("--set-lanes", type=int, help="Число полос → permlanes (>= 1)")
    parser.add_argument("--remove-modes", help="Убрать режимы из modes: car или car,bike")
    parser.add_argument("--close-link", action="store_true", help="Закрыть для авто (= remove-modes car)")
    parser.add_argument("--force", action="store_true", help="Разрешить перезапись входного файла")
    parser.add_argument("--dry-run", action="store_true", help="Показать изменения без записи")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    result = apply_modifications(args)
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    # ненулевой код при проблемах
    return 0 if result["status"] in ("written", "dry_run") else 1


if __name__ == "__main__":
    sys.exit(main())
