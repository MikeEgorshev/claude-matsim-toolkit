#!/usr/bin/env python3
"""
matsim_run.py — запуск симуляции MATSim через subprocess с компактным JSON-ответом.

Огромный stdout MATSim пишется в лог-файл, а агенту возвращается только короткий
JSON (статус, exit code, длительность, путь к логу, опционально метрики). Это
держит контекст LLM чистым — он не захлёбывается тоннами вывода итераций.

Длинные прогоны запускай в фоне (в Claude Code — Bash с run_in_background):
инструмент просто работает синхронно и отдаёт JSON по завершении.

Контракт запуска (настраивается под любой проект):
    java -cp <jar> <main-class> [config] [--threads N] [--config:module.param=value ...]
  либо
    java -jar <jar> [config] ...

Примеры:
    # Проверить команду, ничего не запуская
    python matsim_run.py --jar app.jar --main-class org.matsim.project.RunShamalgan \\
        --config scenarios/shamalgan/config.xml --iterations 1 --dry-run

    # Запустить 100 итераций в свою папку и сразу вернуть метрики
    python matsim_run.py --jar app.jar --main-class org.matsim.project.RunShamalgan \\
        --config scenarios/shamalgan/config.xml --iterations 100 \\
        --output runs/exp_100it --threads 7 --summarize

Зависимости: только стандартная библиотека (+ matsim_metrics.py рядом для --summarize).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def build_command(args: argparse.Namespace) -> list[str]:
    """Собрать список аргументов для subprocess из параметров."""
    cmd: list[str] = [args.java]

    if not args.jar:
        raise ValueError("нужен --jar (путь к собранному MATSim jar)")
    if args.main_class:
        cmd += ["-cp", args.jar, args.main_class]
    else:
        cmd += ["-jar", args.jar]

    # Позиционный аргумент — путь к конфигу (если задан)
    if args.config:
        cmd.append(args.config)

    # Типизированные MATSim-оверрайды
    if args.iterations is not None:
        cmd.append(f"--config:controler.lastIteration={args.iterations}")
    if args.output:
        cmd.append(f"--config:controler.outputDirectory={args.output}")

    # Потоки — у RunShamalgan свой флаг --threads, но и --config:*.numberOfThreads сработает
    if args.threads is not None:
        cmd += ["--threads", str(args.threads)]

    # Произвольный passthrough
    if args.extra:
        cmd += args.extra.split()

    return cmd


def _against_cwd(path_str: str, args: argparse.Namespace) -> Path:
    """Склеить относительный путь с --cwd (MATSim пишет относительно рабочей папки запуска)."""
    p = Path(path_str)
    if not p.is_absolute() and args.cwd:
        return Path(args.cwd) / p
    return p


def _resolve_output_dir(args: argparse.Namespace) -> Path | None:
    """Определить папку output для последующего сбора метрик (с учётом --cwd)."""
    if args.output:
        return _against_cwd(args.output, args)
    # Попытаться вытащить из config.xml (controler.outputDirectory)
    cfg = _against_cwd(args.config, args) if args.config else None
    if cfg and cfg.exists():
        try:
            import xml.etree.ElementTree as ET

            root = ET.parse(cfg).getroot()
            for module in root.iter("module"):
                if module.get("name") == "controler":
                    for p in module.iter("param"):
                        if p.get("name") == "outputDirectory":
                            return _against_cwd(p.get("value"), args)
        except Exception:
            return None
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Запуск симуляции MATSim → компактный JSON.")
    parser.add_argument("--jar", required=True, help="Путь к собранному MATSim jar")
    parser.add_argument("--main-class", help="FQCN main-класса (через java -cp). Без него — java -jar")
    parser.add_argument("--config", help="Путь к config.xml (если опущен — дефолт проекта)")
    parser.add_argument("--iterations", type=int, help="Переопределить controler.lastIteration")
    parser.add_argument("--output", help="Переопределить controler.outputDirectory")
    parser.add_argument("--threads", type=int, help="Число потоков")
    parser.add_argument("--java", default="java", help="Исполняемый java (по умолчанию 'java')")
    parser.add_argument("--cwd", help="Рабочая папка запуска (обычно корень MATSim-проекта)")
    parser.add_argument("--timeout", type=int, help="Таймаут в секундах (по умолчанию без лимита)")
    parser.add_argument("--log", help="Файл лога (по умолчанию matsim_run_<time>.log в cwd/output)")
    parser.add_argument("--extra", help="Произвольные доп. аргументы строкой")
    parser.add_argument("--summarize", action="store_true",
                        help="После прогона распарсить метрики из output и включить в JSON")
    parser.add_argument("--dry-run", action="store_true",
                        help="Только показать команду, ничего не запускать")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    try:
        cmd = build_command(args)
    except ValueError as e:
        print(json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False))
        return 1

    if args.dry_run:
        print(json.dumps(
            {"status": "dry_run", "command": cmd, "cwd": args.cwd or str(Path.cwd())},
            ensure_ascii=False, indent=2 if args.pretty else None,
        ))
        return 0

    # Лог-файл
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.log:
        log_path = _against_cwd(args.log, args)
    else:
        # ВАЖНО: лог НЕ кладём внутрь output — MATSim удаляет/пересоздаёт эту папку
        # при старте, и открытый хэндл лога ломает прогон (особенно на Windows).
        # Кладём рядом, в родительскую папку, с именем по имени output.
        out_dir = _resolve_output_dir(args)
        if out_dir:
            log_path = out_dir.parent / f"{out_dir.name}_run_{ts}.log"
        else:
            base = Path(args.cwd) if args.cwd else Path.cwd()
            log_path = base / f"matsim_run_{ts}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    result: dict = {
        "status": "running",
        "command": cmd,
        "log_file": str(log_path),
        "started_at": ts,
    }

    start = time.time()
    try:
        with log_path.open("w", encoding="utf-8", errors="replace") as logf:
            proc = subprocess.run(
                cmd,
                cwd=args.cwd or None,
                stdout=logf,
                stderr=subprocess.STDOUT,
                timeout=args.timeout,
                text=True,
            )
        result["exit_code"] = proc.returncode
        result["status"] = "completed" if proc.returncode == 0 else "failed"
    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
        result["error"] = f"превышен таймаут {args.timeout} c"
    except FileNotFoundError as e:
        result["status"] = "error"
        result["error"] = f"не найден исполняемый файл: {e}"
    except Exception as e:  # noqa: BLE001
        result["status"] = "error"
        result["error"] = str(e)

    result["duration_s"] = round(time.time() - start, 1)

    # Подтянуть хвост лога для диагностики при неуспехе
    if result["status"] not in ("completed",):
        try:
            tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
            result["log_tail"] = tail
        except Exception:
            pass

    # Опционально — метрики
    if args.summarize and result["status"] == "completed":
        out_dir = _resolve_output_dir(args)
        if out_dir and out_dir.is_dir():
            try:
                sys.path.insert(0, str(Path(__file__).parent))
                from matsim_metrics import collect_metrics  # type: ignore

                result["metrics"] = collect_metrics(out_dir)
            except Exception as e:  # noqa: BLE001
                result["metrics_error"] = str(e)
        else:
            result["metrics_error"] = "не удалось определить папку output"

    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
