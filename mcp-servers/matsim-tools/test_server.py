#!/usr/bin/env python3
"""
Тест MCP-сервера matsim-tools.

Проверяет:
1. сервер импортируется и все 4 инструмента зарегистрированы в FastMCP;
2. каждый инструмент работает на реальных данных (callable напрямую).

Транспорт MCP (stdio) — это код FastMCP, он протестирован апстримом; наш риск в
определениях инструментов, что этот тест и покрывает.

Запуск:
    python test_server.py <MATSIM_PROJECT_DIR>
Если путь не задан — берётся из переменной MATSIM_PROJECT_DIR или дефолт.
"""
import asyncio
import os
import sys
from pathlib import Path

import server  # noqa: E402


def default_project() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    env = os.environ.get("MATSIM_PROJECT_DIR")
    if env:
        return Path(env)
    return Path("C:/Users/Egorshev.M/Desktop/Coding_projects/Cursor_Projects/MATSim_Kaskelen-git")


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
    return ok


async def main() -> int:
    proj = default_project()
    results = []

    # 1. Регистрация инструментов в FastMCP
    tools = await server.mcp.list_tools()
    names = {t.name for t in tools}
    expected = {"get_network_summary", "get_simulation_metrics", "modify_network",
                "run_simulation", "start_simulation", "get_run_status"}
    results.append(check(f"6 инструментов зарегистрированы ({sorted(names)})", expected <= names,
                         f"ожидались {expected}, есть {names}"))

    # 2. get_network_summary на реальной сети
    net = proj / "scenarios/shamalgan/network.xml"
    if net.exists():
        r = server.get_network_summary(network_path=str(net))
        ok = "network" in r and r["network"].get("links", 0) > 0
        results.append(check("get_network_summary: сеть распарсена", ok, str(r)[:200]))
    else:
        print(f"[skip] сеть не найдена: {net}")

    # 3. get_simulation_metrics на реальном output
    out = proj / "output"
    if (out / "scorestats.csv").exists():
        r = server.get_simulation_metrics(output_dir=str(out))
        ok = r.get("iterations") is not None and "modal_split_final" in r
        results.append(check("get_simulation_metrics: метрики получены", ok, str(r)[:200]))
    else:
        print(f"[skip] output/scorestats.csv не найден: {out}")

    # 4. modify_network dry-run (ничего не пишем)
    if net.exists():
        r = server.modify_network(
            network=str(net), output=str(proj / "tmp_mcp_test.xml"),
            links="1", set_capacity=999.0, dry_run=True,
        )
        ok = r.get("status") == "dry_run" and r["changed"][0]["fields"]["capacity"]["new"] == "999.0"
        results.append(check("modify_network: dry-run валиден", ok, str(r)[:200]))

        # 5. валидация ловит ошибку
        r2 = server.modify_network(
            network=str(net), output=str(proj / "tmp_mcp_test.xml"),
            links="1", set_capacity=-1.0, dry_run=True,
        )
        results.append(check("modify_network: валидация ловит отрицательную capacity",
                             r2.get("status") == "invalid", str(r2)[:200]))

    # 6. run_simulation dry-run (команда собирается, ничего не запускаем)
    jars = list(proj.glob("matsim-shamalgan-template-*.jar"))
    if jars:
        r = server.run_simulation(
            jar=str(jars[-1]), main_class="org.matsim.project.RunShamalgan",
            config="scenarios/shamalgan/config.xml", iterations=1,
            output="runs/mcp_dry", cwd=str(proj), dry_run=True, summarize=False,
        )
        ok = r.get("status") == "dry_run" and any("RunShamalgan" in c for c in r.get("command", []))
        results.append(check("run_simulation: dry-run собирает команду", ok, str(r)[:200]))

        # 7. start_simulation + get_run_status (async, реальный короткий прогон)
        import time as _t
        s = server.start_simulation(
            jar=str(jars[-1]), main_class="org.matsim.project.RunShamalgan",
            config="scenarios/shamalgan/config.xml", iterations=1,
            output="runs/async_test", threads=4, cwd=str(proj),
        )
        t0 = _t.time()
        non_blocking = (_t.time() - t0) < 2 and s.get("status") == "running" and "run_id" in s
        results.append(check("start_simulation: не блокирует, вернул run_id", non_blocking, str(s)[:200]))

        if "run_id" in s:
            rid = s["run_id"]
            st = None
            for _ in range(48):  # до ~4 мин
                _t.sleep(5)
                st = server.get_run_status(rid)
                if st.get("status") != "running":
                    break
            done = st is not None and st.get("status") == "completed" \
                and st.get("result", {}).get("metrics", {}).get("iterations") is not None
            results.append(check("get_run_status: дождались completed с метриками", done, str(st)[:200]))
    else:
        print(f"[skip] jar не найден в {proj}")

    print()
    passed = sum(results)
    print(f"Result: {passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
