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
from pathlib import Path
from types import SimpleNamespace

# tools/ лежит на два уровня выше: <repo>/tools/
TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

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
    """Запустить симуляцию MATSim и вернуть компактный JSON (статус, метрики).

    Огромный stdout MATSim уходит в лог-файл, агенту возвращается короткий результат.
    ВНИМАНИЕ: длинные прогоны блокируют — для них ставь разумный timeout или гоняй
    малое число итераций. iterations/output/network применяются как штатные
    --config: оверрайды (сам config.xml не меняется). dry_run=True — только показать
    команду. Возвращает status, exit_code, duration_s, log_file и (при summarize)
    распарсенные метрики.
    """
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


if __name__ == "__main__":
    mcp.run()
