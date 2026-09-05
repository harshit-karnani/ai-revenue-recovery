import os
import sys
import json
import joblib
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix, classification_report

# Ensure app is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.payment_simulator import PaymentSimulator
from app.services.ml_features import extract_features
from app.services.regulatory_engine import evaluate_payment
from app.schemas.payment import PaymentEvent

def analyze():
    simulator = PaymentSimulator(seed=42)
    simulated_data = simulator.generate_events(2000)
    
    events = []
    buckets = []
    
    for event_data in simulated_data:
        bucket = event_data.pop("expected_bucket")
        event_data.pop("expected_failure_code", None)
        event = PaymentEvent(**event_data)
        reg_result = evaluate_payment(event)
        if event.attempt_count >= 4 or bucket == "C":
            continue
        events.append(event)
        buckets.append(bucket)
        
    X = extract_features(events)
    y = pd.Series(buckets)
    
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    
    model_path = os.path.join(os.path.dirname(__file__), "..", "models", "recovery_classifier.joblib")
    pipeline = joblib.load(model_path)
    
    # 1. Training metrics
    y_train_pred = pipeline.predict(X_train)
    y_train_proba = pipeline.predict_proba(X_train)
    train_acc = accuracy_score(y_train, y_train_pred)
    train_f1_a = f1_score(y_train, y_train_pred, pos_label="A")
    train_f1_b = f1_score(y_train, y_train_pred, pos_label="B")
    train_cm = confusion_matrix(y_train, y_train_pred, labels=["A", "B"])
    
    # 2. Validation metrics
    y_test_pred = pipeline.predict(X_test)
    y_test_proba = pipeline.predict_proba(X_test)
    test_acc = accuracy_score(y_test, y_test_pred)
    test_cm = confusion_matrix(y_test, y_test_pred, labels=["A", "B"])
    
    report_test = classification_report(y_test, y_test_pred, labels=["A", "B"], output_dict=True)
    
    # 3. Confidence Distribution on Validation
    confidences_test = y_test_proba.max(axis=1)
    
    print("=== MODEL QUALITY REPORT ===")
    print(f"Total dataset: {len(events)} (Train: {len(X_train)}, Val: {len(X_test)})")
    print(f"\n--- Training Metrics ---")
    print(f"Train Accuracy: {train_acc:.4f}")
    print(f"Train F1 (A): {train_f1_a:.4f}, Train F1 (B): {train_f1_b:.4f}")
    print(f"Train Confusion Matrix (A, B):\n{train_cm}")
    
    print(f"\n--- Validation Metrics ---")
    print(f"Validation Accuracy: {test_acc:.4f}")
    print(f"Validation Confusion Matrix (A, B):\n{test_cm}")
    print("\nDetailed Validation Classification Report:")
    for cls in ["A", "B"]:
        print(f"Class {cls}: Precision={report_test[cls]['precision']:.4f}, Recall={report_test[cls]['recall']:.4f}, F1={report_test[cls]['f1-score']:.4f}, Support={report_test[cls]['support']}")
        
    print(f"\n--- Overfitting Analysis ---")
    print(f"Train Acc ({train_acc:.4f}) vs Val Acc ({test_acc:.4f}) -> Delta: {abs(train_acc - test_acc):.4f}")
    
    # 4. Feature Coefficients
    clf = pipeline.named_steps["classifier"]
    preprocessor = pipeline.named_steps["preprocessor"]
    
    cat_encoder = preprocessor.named_transformers_["cat"]
    cat_feature_names = cat_encoder.get_feature_names_out(["decline_code", "payment_method", "subscription_category"])
    num_feature_names = ["amount", "hour_of_day", "day_of_month", "day_of_week", "attempt_count", "in_congestion_window"]
    all_feature_names = num_feature_names + list(cat_feature_names)
    
    coefs = clf.coef_[0]
    intercept = clf.intercept_[0]
    
    coef_df = pd.DataFrame({
        "Feature": all_feature_names,
        "Coefficient (Log-Odds for B)": coefs,
        "Abs_Coefficient": np.abs(coefs)
    }).sort_values(by="Abs_Coefficient", ascending=False)
    
    print(f"\n--- Model Intercept (Class B reference): {intercept:.4f} ---")
    print("\n--- Feature Coefficients (Top to Bottom by Magnitude) ---")
    print(coef_df.to_string(index=False))
    
    # 5. Threshold Sensitivity
    thresholds = [0.65, 0.70, 0.75, 0.80, 0.85]
    print("\n--- Threshold Sensitivity Analysis on Validation Set ---")
    for t in thresholds:
        escalated = (confidences_test < t).sum()
        pct = (escalated / len(confidences_test)) * 100
        accepted = len(confidences_test) - escalated
        print(f"Threshold {t:.2f}: Escalated (< {t:.2f}) = {escalated}/{len(confidences_test)} ({pct:.2f}%), Autonomous (>= {t:.2f}) = {accepted} ({100-pct:.2f}%)")
        
    print(f"\nConfidence Stats: Min={confidences_test.min():.4f}, Median={np.median(confidences_test):.4f}, Mean={confidences_test.mean():.4f}, Max={confidences_test.max():.4f}")

if __name__ == "__main__":
    analyze()
