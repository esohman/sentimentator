#!/usr/bin/env python3
"""Export EmoMap annotations, wheel points, and exact trial schedules."""

import argparse
import csv
from pathlib import Path

from sentimentator.app import app
from sentimentator.model import Annotation, ParticipantStudy, ParticipantStudyItem, Study, db


def participant_label(participant):
    return f"P{participant.id:05d}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output_prefix", nargs="?", default="emomap_export")
    parser.add_argument("--study-key")
    parser.add_argument("--version")
    parser.add_argument("--include-usernames", action="store_true")
    args = parser.parse_args()

    prefix = Path(args.output_prefix)
    annotations_path = prefix.with_name(prefix.name + "_annotations.csv")
    points_path = prefix.with_name(prefix.name + "_points.csv")
    schedule_path = prefix.with_name(prefix.name + "_schedule.csv")

    with app.app_context():
        study_query = Study.query
        if args.study_key:
            study_query = study_query.filter_by(study_key=args.study_key)
        if args.version:
            study_query = study_query.filter_by(version=str(args.version))
        studies = study_query.order_by(Study.id).all()
        study_ids = [study.id for study in studies]
        if not study_ids:
            raise SystemExit("No matching study found")

        with annotations_path.open("w", newline="", encoding="utf-8") as handle:
            fields = [
                "annotation_id", "study_key", "study_version", "participant_id", "participant_study_id",
                "arm", "trial_number", "item_id", "item_key", "target", "text", "language", "condition",
                "sense", "source", "target_group", "base_item_key", "coarse_label", "association_count",
                "response_time_ms", "scheme_version", "wheel_version", "trial_started_at", "submitted_at",
                "metadata_json",
            ]
            if args.include_usernames:
                fields.insert(4, "username")
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()

            annotations = (
                Annotation.query.join(ParticipantStudyItem)
                .join(ParticipantStudy)
                .filter(ParticipantStudy.study_id.in_(study_ids))
                .order_by(ParticipantStudy.id, ParticipantStudyItem.trial_number)
                .all()
            )
            for annotation in annotations:
                trial = annotation.trial
                participant = trial.participant_study
                study = participant.study
                item = annotation.item
                row = {
                    "annotation_id": annotation.id,
                    "study_key": study.study_key,
                    "study_version": study.version,
                    "participant_id": participant_label(participant),
                    "participant_study_id": participant.id,
                    "arm": participant.arm,
                    "trial_number": trial.trial_number,
                    "item_id": item.id,
                    "item_key": item.item_key,
                    "target": item.target,
                    "text": item.text,
                    "language": item.language,
                    "condition": item.condition,
                    "sense": item.sense or "",
                    "source": item.source or "",
                    "target_group": item.target_group,
                    "base_item_key": item.base_item_key or "",
                    "coarse_label": annotation.coarse_label,
                    "association_count": annotation.association_count,
                    "response_time_ms": annotation.response_time_ms if annotation.response_time_ms is not None else "",
                    "scheme_version": annotation.scheme_version,
                    "wheel_version": annotation.wheel_version,
                    "trial_started_at": trial.started_at.isoformat() if trial.started_at else "",
                    "submitted_at": annotation.created_at.isoformat() if annotation.created_at else "",
                    "metadata_json": item.metadata_json,
                }
                if args.include_usernames:
                    row["username"] = participant.user._user
                writer.writerow(row)

        with points_path.open("w", newline="", encoding="utf-8") as handle:
            fields = [
                "annotation_id", "participant_id", "trial_number", "item_key", "point_order",
                "x_norm", "y_norm", "canonical_x", "canonical_y", "dx", "dy", "radius", "angle_deg",
                "wheel_version",
            ]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for annotation in annotations:
                participant = annotation.trial.participant_study
                for point in annotation.points:
                    writer.writerow({
                        "annotation_id": annotation.id,
                        "participant_id": participant_label(participant),
                        "trial_number": annotation.trial.trial_number,
                        "item_key": annotation.item.item_key,
                        "point_order": point.point_order,
                        "x_norm": point.x_norm,
                        "y_norm": point.y_norm,
                        "canonical_x": point.canonical_x,
                        "canonical_y": point.canonical_y,
                        "dx": point.dx,
                        "dy": point.dy,
                        "radius": point.radius,
                        "angle_deg": point.angle_deg,
                        "wheel_version": annotation.wheel_version,
                    })

        with schedule_path.open("w", newline="", encoding="utf-8") as handle:
            fields = [
                "study_key", "study_version", "participant_id", "participant_study_id", "arm",
                "schedule_seed", "trial_number", "item_key", "target", "condition", "sense", "prime_arm",
                "started_at", "completed_at",
            ]
            if args.include_usernames:
                fields.insert(4, "username")
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            participants = (
                ParticipantStudy.query.filter(ParticipantStudy.study_id.in_(study_ids))
                .order_by(ParticipantStudy.id).all()
            )
            for participant in participants:
                for trial in participant.trials:
                    item = trial.item
                    row = {
                        "study_key": participant.study.study_key,
                        "study_version": participant.study.version,
                        "participant_id": participant_label(participant),
                        "participant_study_id": participant.id,
                        "arm": participant.arm,
                        "schedule_seed": participant.schedule_seed,
                        "trial_number": trial.trial_number,
                        "item_key": item.item_key,
                        "target": item.target,
                        "condition": item.condition,
                        "sense": item.sense or "",
                        "prime_arm": item.prime_arm or "",
                        "started_at": trial.started_at.isoformat() if trial.started_at else "",
                        "completed_at": trial.completed_at.isoformat() if trial.completed_at else "",
                    }
                    if args.include_usernames:
                        row["username"] = participant.user._user
                    writer.writerow(row)

    print(f"Wrote {annotations_path}")
    print(f"Wrote {points_path}")
    print(f"Wrote {schedule_path}")


if __name__ == "__main__":
    main()
