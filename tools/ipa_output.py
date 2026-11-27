"""Install verified IPA builds and their reports without replacing existing files."""

import hashlib
import json
import os


def install_file(candidate, path, check_existing):
    try:
        if os.name == "nt":
            candidate.rename(path)
        else:
            os.link(candidate, path)
    except FileExistsError:
        check_existing(path)


def publish_build(candidate, output, report):
    """The candidate is a verified file in a temporary directory on the output volume."""
    if output.suffix.lower() != ".ipa":
        raise ValueError("output must be an .ipa filename")
    report_path = output.with_suffix(".report.json")

    def check_ipa(path):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != report["output"]["sha256"].lower():
            raise ValueError(f"existing IPA differs: {path}")

    def check_report(path):
        try:
            previous = json.loads(path.read_text(encoding="utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError):
            previous = None
        if previous != report:
            raise ValueError(f"existing report differs: {path}")

    report_stage = candidate.with_suffix(".report.json")
    report_stage.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="\n")
    missing = []
    for staged, target, check in ((candidate, output, check_ipa),
                                  (report_stage, report_path, check_report)):
        if os.path.lexists(target):
            check(target)
        else:
            missing.append((staged, target, check))
    # Validate both destinations first. A retry can fill a missing report after interruption.
    for staged, target, check in missing:
        install_file(staged, target, check)
