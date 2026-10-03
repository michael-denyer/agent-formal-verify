#!/usr/bin/env python3
# Copyright (c) 2026 Michael Denyer
# SPDX-License-Identifier: GPL-3.0-only
"""Run the pinned Kani and validate its versioned discovery and result records."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


class CheckError(Exception):
    pass


class Unavailable(Exception):
    pass


class Kani:
    version = "0.68.0"

    def __init__(self):
        home = Path(os.environ.get("KANI_HOME", Path.home() / ".kani")).resolve()
        bundle = home / f"kani-{self.version}"
        remedy = (f"run cargo install --locked kani-verifier --version {self.version} "
                  "then cargo kani setup")
        for binary in ("bin/kani-driver", "bin/kani-compiler", "bin/cbmc", "toolchain/bin/rustc", "toolchain/bin/cargo"):
            path = bundle / binary
            if not path.is_file() or not os.access(path, os.X_OK):
                raise Unavailable(f"Kani {self.version} bundle is incomplete; {remedy}")
        if any(home.glob("*.tar.gz")):
            raise Unavailable(f"incomplete Kani setup at {home}; finish cargo kani setup before checking")
        self.driver = bundle / "bin/kani-driver"
        self.env = os.environ.copy()
        self.env["KANI_HOME"] = str(home)
        self.env["RUSTUP_TOOLCHAIN"] = str((bundle / "toolchain").resolve())
        for variable, directories in {
            "PATH": [bundle / "bin", bundle / "pyroot/bin", bundle / "toolchain/bin"],
            "PYTHONPATH": [bundle / "pyroot"],
        }.items():
            inherited = [self.env[variable]] if variable in self.env else []
            self.env[variable] = os.pathsep.join([*(str(path) for path in directories), *inherited])
        loader = "DYLD_FALLBACK_LIBRARY_PATH" if sys.platform == "darwin" else "LD_LIBRARY_PATH"
        if loader in self.env:
            self.env[loader] = os.pathsep.join(
                path for path in self.env[loader].split(os.pathsep)
                if not (Path(path).name == "lib" and Path(path).parent.parent.name == "toolchains"))
        try:
            done = self.run("--version")
        except CheckError as error:
            raise Unavailable(f"Kani {self.version} cannot run: {error}; {remedy}") from error
        if done.returncode or not done.stdout.startswith(f"Kani Rust Verifier {self.version} (cargo plugin)\n"):
            raise Unavailable(f"Kani {self.version} is required; {remedy}")

    def run(self, *arguments, cwd=None):
        try:
            # The driver selects Cargo mode from argv[0]; the Cargo wrapper can auto-install.
            return subprocess.run(
                ["cargo-kani", *arguments], executable=str(self.driver), env=self.env,
                cwd=cwd, capture_output=True, text=True, check=False)
        except OSError as error:
            raise CheckError(f"cannot execute Kani: {error}") from error


def invoke(crate, work, kani, *arguments):
    return kani.run("--manifest-path", str(crate / "Cargo.toml"),
                    "--target-dir", str(work / "target"), *arguments, cwd=work)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CheckError(f"missing or invalid Kani report {path.name}: {error}") from error


def discover(crate, work, kani):
    if not (crate / "Cargo.toml").is_file():
        raise CheckError(f"{crate}/Cargo.toml is missing")
    done = invoke(crate, work, kani, "list", "--format", "json")
    if done.returncode:
        raise CheckError(f"Kani discovery failed:\n{done.stdout}{done.stderr}")
    report = read_json(work / "kani-list.json")
    if report.get("kani-version") != kani.version or report.get("file-version") != "0.1":
        raise CheckError("unsupported Kani discovery schema or version")
    groups = report.get("standard-harnesses")
    if not isinstance(groups, dict) or not all(
            isinstance(names, list) and all(isinstance(name, str) and name for name in names)
            for names in groups.values()):
        raise CheckError("malformed Kani harness list")
    names = [name for group in groups.values() for name in group]
    if not names:
        raise CheckError("no proof harnesses found")
    if len(set(names)) != len(names):
        raise CheckError("duplicate harness names; select a single crate")
    bounds = {}
    for metadata in (work / "target").rglob("*.kani-metadata.json"):
        for harness in read_json(metadata).get("proof_harnesses", []):
            name = harness.get("pretty_name")
            if name in names:
                bound = harness.get("attributes", {}).get("unwind_value")
                if type(bound) is not int or bound < 1:
                    raise CheckError(f"{name} needs #[kani::unwind(N)] with N greater than zero")
                bounds[name] = bound
    if set(bounds) != set(names):
        raise CheckError("Kani did not report unwind metadata for every harness")
    return bounds


def verify(crate, work, kani, name, bound):
    result_file = work / "result.json"
    result_file.unlink(missing_ok=True)
    try:
        done = invoke(crate, work, kani, "--harness", name, "--exact", "--unwind", str(bound),
                      "-Z", "unstable-options", "--export-json", str(result_file),
                      "-Z", "concrete-playback", "--concrete-playback", "print",
                      "--output-format", "regular")
    except CheckError as error:
        return False, 0, [str(error)], "", False
    output = done.stdout + done.stderr
    try:
        report = read_json(result_file)
        if report.get("metadata", {}).get("version") != "1.0" or report["metadata"].get("kani_version") != kani.version:
            raise CheckError("unsupported Kani result schema or version")
        verification = report["verification_results"]
        summary, results = verification["summary"], verification["results"]
        if summary["status"] != "completed" or summary["executed"] != 1 or summary["total_harnesses"] != 1:
            raise CheckError("incomplete Kani verification")
        if len(results) != 1 or results[0]["harness_id"] != name:
            raise CheckError("Kani returned an unexpected harness")
        result = results[0]
        checks = result["checks"]
        if not isinstance(checks, list) or not checks:
            raise CheckError("Kani returned no property checks")
        failures = []
        property_failure = False
        incomplete = False
        for check in checks:
            category, status = check["category"], check["status"]
            if status not in {"Success", "Failure", "Unreachable", "Undetermined", "Satisfied", "Unsatisfiable"}:
                raise CheckError(f"unknown Kani check status {status}")
            good = status == "Satisfied" if category == "cover" else status in {"Success", "Unreachable"}
            if not good:
                refuted = (category == "cover" and status in {"Unsatisfiable", "Unreachable"}
                           or category not in {"cover", "unwind"} and status == "Failure")
                property_failure |= refuted
                incomplete |= not refuted
                location = check["location"]
                reason = "bound too low: " if category == "unwind" else ""
                failures.append(f"{reason}{category} {status}: {check['description']} at "
                                f"{location['file']}:{location['line']}:{location['column']}")
        if result["status"] not in {"Success", "Failure"}:
            raise CheckError("unknown Kani harness status")
        expected_failure = result["status"] == "Failure"
        if done.returncode != int(expected_failure) or summary["failed"] != int(expected_failure) \
                or summary["successful"] != int(not expected_failure):
            raise CheckError("Kani process and result disagree")
        if failures:
            return False, len(checks), failures, output, property_failure and not incomplete
        if done.returncode or result["status"] != "Success" or summary["failed"] != 0 or summary["successful"] != 1:
            raise CheckError("Kani process and result disagree")
        return True, len(checks), [], output, False
    except (KeyError, TypeError, AttributeError, CheckError) as error:
        return False, 0, [f"verification did not complete: {error}"], output, False


def main():
    arguments = sys.argv[1:]
    if arguments != ["--ready"] and (len(arguments) < 2 or arguments[0] != "--check"):
        print("usage: bmc.py --ready | --check <crate-dir> [<harness> ...]")
        return 2
    try:
        kani = Kani()
    except Unavailable as error:
        print(f"UNAVAILABLE {error}")
        return 3
    if arguments == ["--ready"]:
        print(f"READY Kani {kani.version}")
        return 0
    _, directory, *selected = arguments
    crate = Path(directory).resolve()
    with tempfile.TemporaryDirectory(prefix="formal-kani-") as temporary:
        work = Path(temporary)
        try:
            bounds = discover(crate, work, kani)
            names = list(dict.fromkeys(selected)) if selected else sorted(bounds)
            unknown = set(names) - set(bounds)
            if unknown:
                raise CheckError("unknown harnesses: " + ", ".join(sorted(unknown)))
        except (CheckError, KeyError, TypeError, AttributeError) as error:
            print(f"FAIL {error}")
            return 1
        passed = 0
        for name in names:
            success, count, failures, output, _ = verify(crate, work, kani, name, bounds[name])
            passed += success
            print(f"{'PASS' if success else 'FAIL'} {name} unwind={bounds[name]} checks={count}"
                  + (": " + "; ".join(failures) if failures else ""))
            if not success:
                print(output.rstrip())
        print(f"SUMMARY {passed} of {len(names)} harnesses passed")
        return 0 if passed == len(names) else 1


if __name__ == "__main__":
    sys.exit(main())
