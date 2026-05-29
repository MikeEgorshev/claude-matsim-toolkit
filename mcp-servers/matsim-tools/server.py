#!/usr/bin/env python3
"""
MCP-сервер matsim-tools — нативные инструменты MATSim для LLM-агента.

Тонкая обёртка над протестированными функциями из ../../tools/. Доменная логика
не дублируется: read-only и modify зовут импортированные функции напрямую, run
запускается как subprocess (он и так процесс-лаунчер). Каждый инструмент отдаёт
компактный dict (MCP сериализует в JSON) — агент не читает сырой XML/CSV.

Запуск как MCP-сервер (stdio):
    python server.py

Регистрация в Claude Code — см. README.md рядом.

Зависимость: пакет `mcp` (FastMCP). Сами tools/ — на чистом stdlib.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

# tools/ лежит на два уровня выше: <repo>/tools/
TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

# Реестр фоновых прогонов (для launch-and-poll). В домашней папке, чтобы
# get_run_status находил прогон по run_id независимо от cwd.
RUNS_REGISTRY = Path.home() / ".matsim_runs"

from matsim_metrics import collect_metrics  # noqa: E402
from matsim_modify import apply_modifications  # noqa: E402
from matsim_summary import summarize_network, summarize_plans  # noqa: E402

from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP("matsim-tools")


@mcp.tool()
def get_network_summary(network_path: str = "", plans_path: str = "") -> dict:
    """Компактная сводка MATSim-сети и/или планов (поддержка .gz).

    Возвращает число узлов/звеньев, диапазоны freespeed (м/с) и capacity (авт/ч),
    типы дорог, размер популяции, типы активностей, режимы поездок. Предупреждает
    о freespeed > 50 м/с (вероятно значение случайно в км/ч).

    Укажи network_path и/или plans_path (хотя бы один).
    """
    result: dict = {}
    if network_path:
        p = Path(network_path)
        result["network"] = summarize_network(p) if p.exists() else {"error": f"не найден: {network_path}"}
    if plans_path:
        p = Path(plans_path)
        result["plans"] = summarize_plans(p) if p.exists() else {"error": f"не найден: {plans_path}"}
    if not result:
        return {"error": "укажи network_path и/или plans_path"}
    return result


@mcp.tool()
def get_simulation_metrics(output_dir: str) -> dict:
    """Метрики результата симуляции из штатных CSV MATSim.

    Парсит scorestats/modestats/traveldistancestats в output_dir и возвращает:
    число итераций, эволюцию score (начало/конец/дельта), modal split (начальный
    и финальный), среднюю дальность поездки. Это контур обратной связи для оценки
    «стала ли модель лучше».
    """
    p = Path(output_dir)
    if not p.is_dir():
        return {"error": f"не папка: {output_dir}"}
    return collect_metrics(p)


@mcp.tool()
def modify_network(
    network: str,
    output: str,
    links: str,
    set_capacity: float | None = None,
    set_freespeed: float | None = None,
    set_freespeed_kmh: float | None = None,
    set_lanes: int | None = None,
    remove_modes: str = "",
    close_link: bool = False,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    """Типизированно изменить MATSim network.xml с валидацией ДО записи.

    Пишет в КОПИЮ (output), оригинал не трогает (перезапись только force=True),
    сохраняет DOCTYPE. links — id звеньев через запятую ("456" или "12,13,14").
    Операции комбинируются: set_capacity (авт/ч, >0), set_freespeed (м/с, >0),
    set_freespeed_kmh (÷3.6), set_lanes (→permlanes, >=1), remove_modes ("car"
    или "car,bike"), close_link (= убрать car). dry_run=True показывает изменения
    без записи. Возвращает список изменений (старое→новое) и предупреждения.
    """
    args = SimpleNamespace(
        network=network,
        output=output,
        links=links,
        set_capacity=set_capacity,
        set_freespeed=set_freespeed,
        set_freespeed_kmh=set_freespeed_kmh,
        set_lanes=set_lanes,
        remove_modes=remove_modes or None,
        close_link=close_link,
        force=force,
        dry_run=dry_run,
    )
    return apply_modifications(args)


def _matsim_run_cmd(
    jar: str, config: str, main_class: str, iterations: int | None, output: str,
    network: str, threads: int | None, cwd: str, timeout: int | None,
    summarize: bool, dry_run: bool,
) -> list[str]:
    """Собрать argv для CLI tools/matsim_run.py (общий для sync и async путей)."""
    cmd = [sys.executable, str(TOOLS_DIR / "matsim_run.py"), "--jar", jar]
    if main_class:
        cmd += ["--main-class", main_class]
    if config:
        cmd += ["--config", config]
    if iterations is not None:
        cmd += ["--iterations", str(iterations)]
    if output:
        cmd += ["--output", output]
    if network:
        cmd += ["--network", network]
    if threads is not None:
        cmd += ["--threads", str(threads)]
    if cwd:
        cmd += ["--cwd", cwd]
    if timeout is not None:
        cmd += ["--timeout", str(timeout)]
    if summarize:
        cmd += ["--summarize"]
    if dry_run:
        cmd += ["--dry-run"]
    return cmd


@mcp.tool()
def run_simulation(
    jar: str,
    config: str = "",
    main_class: str = "",
    iterations: int | None = None,
    output: str = "",
    network: str = "",
    threads: int | None = None,
    cwd: str = "",
    timeout: int | None = None,
    summarize: bool = True,
    dry_run: bool = False,
) -> dict:
    """Запустить симуляцию СИНХРОННО (блокирует) — только для dry_run и коротких
    smoke-прогонов (≤ нескольких итераций).

    ВНИМАНИЕ: блокирует вызов на всё время прогона. Для реальных/длинных прогонов
    используй start_simulation + get_run_status (не блокирует, обходит таймаут MCP).
    iterations/output/network — штатные --config: оверрайды (config.xml не меняется).
    Возвращает status, exit_code, duration_s, log_file и (при summarize) метрики.
    """
    cmd = _matsim_run_cmd(jar, config, main_class, iterations, output, network,
                          threads, cwd, timeout, summarize, dry_run)
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env
        )
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"status": "error", "error": "не удалось распарсить вывод matsim_run",
                "stdout_tail": (proc.stdout or "")[-1500:], "stderr_tail": (proc.stderr or "")[-1500:]}
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "error": str(e)}


@mcp.tool()
def start_simulation(
    jar: str,
    config: str = "",
    main_class: str = "",
    iterations: int | None = None,
    output: str = "",
    network: str = "",
    threads: int | None = None,
    cwd: str = "",
    summarize: bool = True,
) -> dict:
    """Запустить симуляцию В ФОНЕ и сразу вернуть run_id (НЕ блокирует).

    Правильный путь для реальных/длинных прогонов: вызов возвращается мгновенно,
    симуляция крутится в фоне, финальный JSON пишется в файл. Потом проверяй
    get_run_status(run_id) — он отдаст 'running' или финальные метрики.
    iterations/output/network — штатные --config: оверрайды (config.xml не меняется).
    """
    RUNS_REGISTRY.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    result_file = RUNS_REGISTRY / f"{run_id}.result.json"
    err_file = RUNS_REGISTRY / f"{run_id}.err"
    meta_file = RUNS_REGISTRY / f"{run_id}.meta.json"

    # summarize=True чтобы фоновый прогон сразу сложил метрики в результат
    cmd = _matsim_run_cmd(jar, config, main_class, iterations, output, network,
                          threads, cwd, None, summarize, False)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    out_fh = open(result_file, "w", encoding="utf-8")
    err_fh = open(err_file, "w", encoding="utf-8")
    try:
        creationflags = subprocess.DETACHED_PROCESS if os.name == "nt" else 0
        proc = subprocess.Popen(
            cmd, cwd=cwd or None, stdout=out_fh, stderr=err_fh, env=env,
            creationflags=creationflags,
        )
    finally:
        out_fh.close()
        err_fh.close()

    meta = {
        "run_id": run_id, "pid": proc.pid, "command": cmd, "cwd": cwd,
        "result_file": str(result_file), "err_file": str(err_file),
        "started_at": time.time(), "started_at_h": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    meta_file.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    return {
        "run_id": run_id,
        "status": "running",
        "started_at": meta["started_at_h"],
        "message": "Симуляция запущена в фоне. Проверяй статус через get_run_status(run_id).",
    }


@mcp.tool()
def get_run_status(run_id: str) -> dict:
    """Статус фонового прогона по run_id (из start_simulation).

    Возвращает status='running' (с elapsed_s) пока идёт, либо финальный результат
    (status + метрики) когда завершился. Определяет завершение по наличию валидного
    JSON в файле результата — кросс-платформенно, без проверки pid.
    """
    meta_file = RUNS_REGISTRY / f"{run_id}.meta.json"
    if not meta_file.exists():
        return {"run_id": run_id, "status": "unknown", "error": "нет такого run_id в реестре"}

    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    elapsed = round(time.time() - meta["started_at"], 1)
    result_file = Path(meta["result_file"])
    content = result_file.read_text(encoding="utf-8").strip() if result_file.exists() else ""

    if content:
        try:
            result = json.loads(content)
            return {"run_id": run_id, "status": result.get("status", "completed"),
                    "elapsed_s": elapsed, "result": result}
        except json.JSONDecodeError:
            err = ""
            err_file = Path(meta["err_file"])
            if err_file.exists():
                err = err_file.read_text(encoding="utf-8", errors="replace")[-1000:]
            return {"run_id": run_id, "status": "error", "elapsed_s": elapsed,
                    "error": "вывод не JSON (возможно сбой)", "stdout_tail": content[-1000:],
                    "stderr_tail": err}

    # результат пуст — либо ещё идёт, либо лаунчер упал до вывода (есть traceback)
    err_file = Path(meta["err_file"])
    if err_file.exists():
        err = err_file.read_text(encoding="utf-8", errors="replace")
        if "Traceback" in err:
            return {"run_id": run_id, "status": "error", "elapsed_s": elapsed,
                    "error": "лаунчер завершился с ошибкой до вывода результата",
                    "stderr_tail": err[-1000:]}
    return {"run_id": run_id, "status": "running", "elapsed_s": elapsed}


if __name__ == "__main__":
    mcp.run()
