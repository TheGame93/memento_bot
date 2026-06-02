import json
import os
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable


@dataclass
class DebugHarness:
    script_file: str
    script_title: str
    feature_title: str
    args: list[str]
    verbose: bool
    quiet: bool
    log_path: str
    log_file: object
    problems: list[str] = field(default_factory=list)
    dependency_failed: bool = False

    @classmethod
    def create(cls, script_file: str, script_title: str, feature_title: str, args: list[str] | None = None):
        parsed_args = list(sys.argv[1:] if args is None else args)
        verbose = "--verbose" in parsed_args
        quiet = "--quiet" in parsed_args and not verbose
        script_name = os.path.splitext(os.path.basename(script_file))[0]
        log_path = os.path.join(_debug_log_dir(script_file), f"{script_name}.log")
        log_file = open(log_path, "w", encoding="utf-8", errors="replace")
        return cls(
            script_file=script_file,
            script_title=script_title,
            feature_title=feature_title,
            args=parsed_args,
            verbose=verbose,
            quiet=quiet,
            log_path=log_path,
            log_file=log_file,
        )

    def write_log(self, line: str):
        if self.log_file:
            self.log_file.write(line + "\n")
            self.log_file.flush()

    def section(self, label: str, payload: dict):
        record = {"section": label, **payload}
        rendered = json.dumps(record, indent=2, default=str)
        self.write_log(rendered)
        if self.verbose:
            print(rendered)

    def run_meta(self, extra: dict | None = None):
        payload = {
            "run_time": datetime.now().isoformat(),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "log_file": self.log_path,
        }
        if extra:
            payload.update(extra)
        self.section("run_meta", payload)

    def problem(self, message: str, payload: dict | None = None):
        self.problems.append(message)
        record = {"section": "problem", "message": message, "payload": payload or {}}
        self.write_log(json.dumps(record, indent=2, default=str))

    def has_problem(self, *codes: str) -> bool:
        return any(code in self.problems for code in codes)

    def mark_dependency_error(self, exc: Exception, hint: str = "Missing dependencies. Activate venv and install requirements."):
        self.dependency_failed = True
        self.write_log(json.dumps({
            "section": "dependency_error",
            "error": str(exc),
            "hint": hint,
        }, indent=2, default=str))
        if not self.quiet:
            print(f"{self.script_title} failed. See {self.log_path} for details.")

    def print_summary(self, lines: Iterable[str], only_if_problems: bool = False):
        if self.quiet:
            return
        if only_if_problems and not self.problems:
            return
        print(f"[{self.script_title}] {self.feature_title}")
        for line in lines:
            print(f"- {line}")

    def close(self):
        if self.log_file:
            try:
                self.log_file.close()
            finally:
                self.log_file = None

    def finish(
        self,
        *,
        summary_lines: Iterable[str] | None = None,
        summary_only_on_problems: bool = False,
        exit_on_problems: bool = True,
    ):
        if summary_lines is not None:
            self.print_summary(summary_lines, only_if_problems=summary_only_on_problems)
        self.close()
        if self.dependency_failed:
            raise SystemExit(1)
        if exit_on_problems and self.problems:
            raise SystemExit(1)
        return 1 if self.problems else 0


def _tests_dir_from_script(script_file: str) -> str:
    current = os.path.abspath(os.path.dirname(script_file))
    while True:
        if os.path.basename(current) == "tests":
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.abspath(os.path.join(os.path.dirname(script_file), "..", ".."))
        current = parent


def _debug_log_dir(script_file: str) -> str:
    log_dir = os.path.join(_tests_dir_from_script(script_file), "log")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir
