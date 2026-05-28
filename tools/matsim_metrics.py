#!/usr/bin/env python3
"""
matsim_metrics.py — парсер штатных output-CSV MATSim в компактный JSON.

MATSim сам пишет scorestats.csv / modestats.csv / traveldistancestats.csv
(разделитель ';'). Этот инструмент сводит их в один JSON для LLM-агента,
чтобы тот оценивал результат симуляции без чтения сырых файлов.

Использование:
    python matsim_metrics.py <output_dir>
    python matsim_metrics.py <output_dir> --pretty

Зависимости: только стандартная библиотека.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path


def _read_semicolon_csv(path: Path) -> list[dict[str, str]]:
    """Прочитать ;-разделённый CSV MATSim. Пустой список если файла нет."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def _to_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _iter_key(row: dict[str, str]) -> str | None:
    """Найти колонку итерации без учёта регистра (iteration / ITERATION)."""
    for k in row:
        if k.lower() == "iteration":
            return k
    return None


def _iter_value(row: dict[str, str]) -> float | None:
    key = _iter_key(row)
    return _to_float(row.get(key)) if key else None


def _data_columns(rows: list[dict[str, str]]) -> list[str]:
    """Все колонки кроме итерации (без учёта регистра)."""
    if not rows:
        return []
    return [c for c in rows[0].keys() if c.lower() != "iteration"]


def _first_last(rows: list[dict[str, str]], column: str) -> tuple[float | None, float | None]:
    """Значение column в первой и последней строке (по порядку итераций)."""
    vals = [(_iter_value(r), _to_float(r.get(column))) for r in rows]
    vals = [(i, v) for i, v in vals if i is not None and v is not None]
    if not vals:
        return None, None
    vals.sort(key=lambda t: t[0])
    return vals[0][1], vals[-1][1]


def _round(value: float | None, ndigits: int = 4) -> float | None:
    return None if value is None else round(value, ndigits)


def collect_metrics(output_dir: Path) -> dict:
    result: dict = {"output_dir": str(output_dir), "warnings": []}

    # --- scorestats.csv ---
    score_rows = _read_semicolon_csv(output_dir / "scorestats.csv")
    if score_rows:
        iters = [_iter_value(r) for r in score_rows]
        iters = [i for i in iters if i is not None]
        result["iterations"] = int(max(iters)) if iters else None
        # MATSim newer: avg_executed; older: executed
        score_col = "avg_executed" if "avg_executed" in score_rows[0] else (
            "executed" if "executed" in score_rows[0] else None
        )
        if score_col:
            ini, fin = _first_last(score_rows, score_col)
            result["score"] = {
                "initial": _round(ini, 2),
                "final": _round(fin, 2),
                "delta": _round((fin - ini) if (ini is not None and fin is not None) else None, 2),
                "column": score_col,
            }
        else:
            result["warnings"].append("scorestats.csv: не найдена колонка avg_executed/executed")
    else:
        result["warnings"].append("scorestats.csv не найден")

    # --- modestats.csv (доли по режимам) ---
    mode_rows = _read_semicolon_csv(output_dir / "modestats.csv")
    if mode_rows:
        mode_cols = _data_columns(mode_rows)
        first_row = min(mode_rows, key=lambda r: _iter_value(r) or 0)
        last_row = max(mode_rows, key=lambda r: _iter_value(r) or 0)
        result["modal_split_initial"] = {
            c: _round(_to_float(first_row.get(c))) for c in mode_cols
        }
        result["modal_split_final"] = {
            c: _round(_to_float(last_row.get(c))) for c in mode_cols
        }
    else:
        result["warnings"].append("modestats.csv не найден")

    # --- traveldistancestats.csv ---
    dist_rows = _read_semicolon_csv(output_dir / "traveldistancestats.csv")
    if dist_rows:
        dist_cols = _data_columns(dist_rows)
        # предпочесть колонку про trip distance, иначе первую доступную
        dist_col = next((c for c in dist_cols if "trip" in c.lower()), None) or (
            dist_cols[0] if dist_cols else None
        )
        if dist_col:
            ini, fin = _first_last(dist_rows, dist_col)
            result["travel_distance_avg_m"] = {
                "initial": _round(ini, 1),
                "final": _round(fin, 1),
                "column": dist_col,
            }

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Свести output-метрики MATSim в JSON.")
    parser.add_argument("output_dir", help="Папка output MATSim (со scorestats.csv и др.)")
    parser.add_argument("--pretty", action="store_true", help="Читаемый отступ JSON")
    args = parser.parse_args(argv)

    out_dir = Path(args.output_dir)
    if not out_dir.is_dir():
        print(json.dumps({"error": f"Не папка: {out_dir}"}, ensure_ascii=False))
        return 1

    metrics = collect_metrics(out_dir)
    print(json.dumps(metrics, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
