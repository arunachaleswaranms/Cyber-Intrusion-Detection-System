"""Train reproducible KDD Cup 1999 baseline models."""

from __future__ import annotations

import argparse
from pathlib import Path

import joblib
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.pipeline import Pipeline

from data_preprocessing import build_preprocessor, load_dataset, split_features_target
from model_evaluation import calculate_metrics, print_metrics

RANDOM_STATE = 42


def build_models() -> dict[str, object]:
    return {
        "random_forest": RandomForestClassifier(
            n_estimators=100, random_state=RANDOM_STATE, n_jobs=-1
        ),
        "gradient_boosting": GradientBoostingClassifier(random_state=RANDOM_STATE),
    }


def train_models(train_path: str, output_dir: str, test_path: str | None = None) -> None:
    X_train, y_train = split_features_target(load_dataset(train_path))
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    test_data = split_features_target(load_dataset(test_path)) if test_path else None

    for name, estimator in build_models().items():
        pipeline = Pipeline(
            [("preprocessor", build_preprocessor()), ("classifier", estimator)]
        )
        print(f"Training {name}...")
        pipeline.fit(X_train, y_train)
        model_path = output / f"{name}.joblib"
        joblib.dump(pipeline, model_path)
        print(f"Saved {model_path}")

        if test_data:
            X_test, y_test = test_data
            print_metrics(name, calculate_metrics(pipeline, X_test, y_test))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", required=True, help="KDD Cup training file")
    parser.add_argument("--test", help="Optional held-out test file")
    parser.add_argument("--output-dir", default="models", help="Model output directory")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    train_models(args.train, args.output_dir, args.test)
