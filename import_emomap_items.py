#!/usr/bin/env python3
"""Import a versioned EmoMap master-item CSV into the persistent database.

This importer is intentionally conservative: once any participant schedule has
been created for a study version, stimulus changes are refused.  Create a new
study version instead of silently changing an experiment in progress.
"""

import argparse
import csv
import json
import os
from pathlib import Path

from sentimentator.app import app
from sentimentator.model import ParticipantStudy, Study, StudyItem, db


KNOWN_COLUMNS = {
    "item_key", "language", "target", "text", "context", "condition", "sense",
    "source", "target_group", "base_item_key", "prime_arm", "active", "metadata_json",
}


def parse_bool(value, default=True):
    if value is None or str(value).strip() == "":
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "active"}:
        return True
    if normalized in {"0", "false", "no", "n", "inactive"}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def marked_text(target, text):
    text = text.strip()
    if text.count("[[") == 1 and text.count("]]" ) == 1:
        start = text.index("[[")
        end = text.index("]]", start + 2)
        marked_target = text[start + 2:end]
        if marked_target.lower() != target.lower():
            raise ValueError(
                f"Marked target {marked_target!r} does not match target {target!r} in {text!r}"
            )
        return text

    idx = text.lower().find(target.lower())
    if idx < 0:
        raise ValueError(f"Target {target!r} not found in text {text!r}")
    return text[:idx] + "[[" + text[idx:idx + len(target)] + "]]" + text[idx + len(target):]


def row_metadata(row):
    metadata = {}
    raw = (row.get("metadata_json") or "").strip()
    if raw:
        metadata = json.loads(raw)
        if not isinstance(metadata, dict):
            raise ValueError("metadata_json must contain a JSON object")
    for key, value in row.items():
        if key not in KNOWN_COLUMNS and value is not None and str(value).strip() != "":
            metadata[key] = value
    return metadata


def load_rows(path):
    rows = []
    seen_keys = set()
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV has no header")
        for line_number, row in enumerate(reader, start=2):
            item_key = (row.get("item_key") or "").strip()
            target = (row.get("target") or "").strip()
            text = (row.get("text") or row.get("context") or "").strip()
            condition = (row.get("condition") or "").strip().lower()
            if not item_key or not target or not text or not condition:
                raise ValueError(
                    f"Line {line_number}: item_key, target, text/context and condition are required"
                )
            if item_key in seen_keys:
                raise ValueError(f"Line {line_number}: duplicate item_key {item_key!r}")
            seen_keys.add(item_key)
            if condition not in {"isolated", "context", "control", "repeat"}:
                raise ValueError(f"Line {line_number}: invalid condition {condition!r}")

            prime_arm = (row.get("prime_arm") or "").strip() or None
            if prime_arm and condition != "context":
                raise ValueError(f"Line {line_number}: prime_arm is only valid for context items")

            rows.append({
                "item_key": item_key,
                "language": (row.get("language") or "en").strip() or "en",
                "target": target,
                "text": marked_text(target, text),
                "condition": condition,
                "sense": (row.get("sense") or "").strip() or None,
                "source": (row.get("source") or "").strip() or None,
                "target_group": (row.get("target_group") or target).strip(),
                "base_item_key": (row.get("base_item_key") or "").strip() or None,
                "prime_arm": prime_arm,
                "active": parse_bool(row.get("active"), True),
                "metadata_json": json.dumps(row_metadata(row), ensure_ascii=False, sort_keys=True),
            })

    # Experimental design checks that are easiest to catch before DB writes.
    groups = {}
    for row in rows:
        groups.setdefault(row["target_group"], []).append(row)
    for group, group_rows in groups.items():
        isolated = [r for r in group_rows if r["condition"] == "isolated" and r["active"]]
        if len(isolated) > 1:
            raise ValueError(f"Target group {group!r} has more than one active isolated item")
        by_arm = {}
        for row in group_rows:
            if row["active"] and row["prime_arm"]:
                if row["prime_arm"] in by_arm:
                    raise ValueError(
                        f"Target group {group!r} has multiple primes for arm {row['prime_arm']!r}"
                    )
                by_arm[row["prime_arm"]] = row["item_key"]
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_file")
    parser.add_argument("--study-key", default=os.getenv("EMOMAP_STUDY_KEY", "emomap-pilot"))
    parser.add_argument("--version", default=os.getenv("EMOMAP_STUDY_VERSION", "1"))
    parser.add_argument("--title", default="EmoMap lexical and contextual annotation")
    parser.add_argument(
        "--config-json",
        default='{"arms":{"main":1.0},"min_target_lag":8}',
        help="Study scheduler configuration as JSON",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Deactivate existing study items missing from this CSV (only before study start)",
    )
    args = parser.parse_args()

    config = json.loads(args.config_json)
    if not isinstance(config, dict):
        raise SystemExit("--config-json must be a JSON object")
    rows = load_rows(args.csv_file)

    with app.app_context():
        db.create_all()
        study = Study.query.filter_by(study_key=args.study_key, version=str(args.version)).first()
        if study is None:
            study = Study(
                study_key=args.study_key,
                version=str(args.version),
                title=args.title,
                config_json=json.dumps(config, ensure_ascii=False, sort_keys=True),
                active=True,
            )
            db.session.add(study)
            db.session.flush()
        else:
            if ParticipantStudy.query.filter_by(study_id=study.id).count() > 0:
                raise SystemExit(
                    "REFUSED: participant schedules already exist for this study version. "
                    "Do not mutate an experiment after data collection begins; import under a new version."
                )
            study.title = args.title
            study.config_json = json.dumps(config, ensure_ascii=False, sort_keys=True)
            study.active = True

        imported_keys = set()
        for data in rows:
            imported_keys.add(data["item_key"])
            item = StudyItem.query.filter_by(study_id=study.id, item_key=data["item_key"]).first()
            if item is None:
                item = StudyItem(study_id=study.id, item_key=data["item_key"])
                db.session.add(item)
            for key, value in data.items():
                if key != "item_key":
                    setattr(item, key, value)

        if args.replace:
            for item in StudyItem.query.filter_by(study_id=study.id).all():
                if item.item_key not in imported_keys:
                    item.active = False

        db.session.commit()
        active_count = StudyItem.query.filter_by(study_id=study.id, active=True).count()
        print(
            f"Imported {len(rows)} rows for {study.study_key} v{study.version}; "
            f"{active_count} active study items."
        )
        print("No participant schedule has been created or changed by this command.")


if __name__ == "__main__":
    main()
