"""`python -m bench <command>`."""

import argparse
import datetime
import pathlib

from thursday_bench.runner import FULL


def main() -> None:
    parser = argparse.ArgumentParser(prog="bench")
    sub = parser.add_subparsers(dest="command", required=True)
    fake = sub.add_parser("fake-model", help="serve the fake model")
    fake.add_argument("--port", type=int, required=True)
    run = sub.add_parser("run", help="run the workloads and write the results")
    run.add_argument("--only", help=f"comma-separated workloads: {', '.join(FULL)} (default: all)")
    run.add_argument("--quick", action="store_true", help="small sizes, one run: checks that the harness works")
    run.add_argument("--runs", type=int, help="measured runs per workload (default: the plan in bench/README.md)")
    run.add_argument("--out", help="output folder (default: var/bench/<date>)")
    report = sub.add_parser("report", help="write report.md from a results.json")
    report.add_argument("results")
    charts = sub.add_parser("charts", help="draw the README charts (light and dark SVG) from saved results")
    charts.add_argument("baseline", help="results.json of a full run")
    charts.add_argument("--kill-before", nargs="+", default=[], help="results.json of kill-test runs before a fix")
    charts.add_argument("--kill-after", nargs="+", default=[], help="results.json of kill-test runs after the fix")
    charts.add_argument("--out", default="docs/images", help="output folder (default: docs/images)")
    args = parser.parse_args()
    if args.command == "fake-model":
        from thursday_bench.fake_model import serve

        serve(args.port)
    elif args.command == "run":
        from thursday_bench.report import write as write_report
        from thursday_bench.runner import run as run_all

        names = args.only.split(",") if args.only else list(FULL)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        out = pathlib.Path(args.out or f"var/bench/{stamp}").resolve()
        target = run_all(names, args.quick, args.runs, out)
        print(f"Results: {target}")
        print(f"Report:  {write_report(target)}")
    elif args.command == "report":
        from thursday_bench.report import write as write_report

        print(write_report(pathlib.Path(args.results)))
    elif args.command == "charts":
        from thursday_bench.charts import write as write_charts

        paths = write_charts(
            pathlib.Path(args.baseline),
            [pathlib.Path(p) for p in args.kill_before],
            [pathlib.Path(p) for p in args.kill_after],
            pathlib.Path(args.out),
        )
        for path in paths:
            print(path)


if __name__ == "__main__":
    main()
