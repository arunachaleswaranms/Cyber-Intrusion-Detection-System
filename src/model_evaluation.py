"""Evaluate saved IDS models against a held-out KDD Cup dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

from data_preprocessing import load_dataset, split_features_target


def calculate_metrics(model: object, features, labels) -> dict:
    predictions = model.predict(features)
    return {
        "accuracy": accuracy_score(labels, predictions),
        "classification_report": classification_report(
            labels, predictions, output_dict=True, zero_division=0
        ),
        "confusion_matrix": confusion_matrix(labels, predictions).tolist(),
    }


def print_metrics(model_name: str, metrics: dict) -> None:
    print(f"\nResults for {model_name}")
    print(json.dumps(metrics, indent=2))


def evaluate_models(model_paths: list[str], test_path: str) -> None:
    X_test, y_test = split_features_target(load_dataset(test_path))
    for model_path in model_paths:
        model = joblib.load(model_path)
        print_metrics(Path(model_path).stem, calculate_metrics(model, X_test, y_test))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", required=True, help="Held-out KDD Cup test file")
    parser.add_argument("models", nargs="+", help="One or more saved .joblib pipelines")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    evaluate_models(args.models, args.test)
