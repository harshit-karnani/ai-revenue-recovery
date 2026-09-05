import os
import sys
import json
import joblib
import pandas as pd
from datetime import datetime
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix

# Ensure app is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.payment_simulator import PaymentSimulator
from app.services.ml_features import extract_features
from app.services.regulatory_engine import evaluate_payment
from app.services.rules_classifier import classify_failure

from app.schemas.payment import PaymentEvent

def train_model():
    print("Generating simulated payment data...")
    simulator = PaymentSimulator(seed=42)
    # Generate a larger set to ensure we get enough A/B examples after C is filtered
    simulated_data = simulator.generate_events(2000)
    
    events = []
    buckets = []
    
    print("Filtering Bucket C (Regulatory) failures and extracting labels...")
    for event_data in simulated_data:
        # The simulator returns a dict with expected_bucket and expected_failure_code
        bucket = event_data.pop("expected_bucket")
        event_data.pop("expected_failure_code", None)
        
        # Pydantic parsing
        event = PaymentEvent(**event_data)
        
        # 1. Run regulatory check
        reg_result = evaluate_payment(event)
        
        # 2. Check terminal state
        if event.attempt_count >= 4:
            continue
            
        # Strictly exclude C
        if bucket == "C":
            continue
            
        events.append(event)
        buckets.append(bucket)
        
    print(f"Total valid A/B events generated: {len(events)}")
    if len(events) == 0:
        raise ValueError("No A/B events generated! Check simulator.")
        
    # Extract features using the shared pipeline
    print("Extracting features...")
    X = extract_features(events)
    y = pd.Series(buckets)
    
    # Validation: Ensure no 'C' in targets
    if "C" in set(y):
        raise ValueError("Bucket C found in training targets! This is a strict invariant violation.")
        
    print(f"Class distribution:\n{y.value_counts()}")
    
    # Train/Test Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    
    # Define preprocessing
    numeric_features = ["amount", "hour_of_day", "day_of_month", "day_of_week", "attempt_count", "in_congestion_window"]
    categorical_features = ["decline_code", "payment_method", "subscription_category"]
    
    preprocessor = ColumnTransformer(
        transformers=[
            ("num", "passthrough", numeric_features),
            ("cat", OneHotEncoder(handle_unknown="ignore"), categorical_features),
        ]
    )
    
    # Create pipeline
    pipeline = Pipeline(steps=[
        ("preprocessor", preprocessor),
        ("classifier", LogisticRegression(random_state=42, max_iter=1000))
    ])
    
    print("Training model...")
    pipeline.fit(X_train, y_train)
    
    print("Evaluating model...")
    y_pred = pipeline.predict(X_test)
    y_proba = pipeline.predict_proba(X_test)
    
    # Calculate confidence as max probability
    confidences = y_proba.max(axis=1)
    
    acc = accuracy_score(y_test, y_pred)
    prec = precision_score(y_test, y_pred, pos_label="B", zero_division=0)
    rec = recall_score(y_test, y_pred, pos_label="B", zero_division=0)
    f1 = f1_score(y_test, y_pred, pos_label="B", zero_division=0)
    cm = confusion_matrix(y_test, y_pred, labels=["A", "B"])
    
    print(f"Accuracy:  {acc:.4f}")
    print(f"Precision (B): {prec:.4f}")
    print(f"Recall (B):    {rec:.4f}")
    print(f"F1 (B):        {f1:.4f}")
    print(f"Confusion Matrix (A, B):\n{cm}")
    
    # Print confidence distribution
    conf_min = confidences.min()
    conf_mean = confidences.mean()
    # using numpy median directly is easier or pandas
    conf_median = pd.Series(confidences).median()
    escalated_count = sum(1 for c in confidences if c < 0.75)
    accepted_count = len(confidences) - escalated_count
    
    print("\n--- Confidence Distribution (Validation Set) ---")
    print(f"Min: {conf_min:.4f}, Median: {conf_median:.4f}, Mean: {conf_mean:.4f}")
    print(f"Accepted (>= 0.75): {accepted_count} ({accepted_count/len(confidences)*100:.1f}%)")
    print(f"Escalated (< 0.75): {escalated_count} ({escalated_count/len(confidences)*100:.1f}%)\n")
    
    # Save model and metadata
    models_dir = os.path.join(os.path.dirname(__file__), "..", "models")
    os.makedirs(models_dir, exist_ok=True)
    
    model_path = os.path.join(models_dir, "recovery_classifier.joblib")
    meta_path = os.path.join(models_dir, "recovery_classifier_metadata.json")
    
    joblib.dump(pipeline, model_path)
    
    # compute congestion distribution for metadata
    congestion_counts = X_train["in_congestion_window"].value_counts().to_dict()
    
    metadata = {
        "model_type": "LogisticRegression (sklearn Pipeline)",
        "training_sample_count": len(y_train),
        "validation_sample_count": len(y_test),
        "classes": pipeline.classes_.tolist(),
        "validation_accuracy": acc,
        "validation_precision": prec,
        "validation_recall": rec,
        "validation_f1": f1,
        "validation_escalated_percent": (escalated_count / len(confidences)) * 100,
        "training_congestion_window_distribution": congestion_counts,
        "training_timestamp": datetime.now().astimezone().isoformat(),
        "random_seed": 42,
        "confidence_threshold": 0.75,
        "features": {
            "numeric": numeric_features,
            "categorical": categorical_features
        }
    }
    
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)
        
    print(f"Model saved to {model_path}")
    print(f"Metadata saved to {meta_path}")
    
    # Final quick validation test
    print("Validating loaded artifact...")
    loaded_model = joblib.load(model_path)
    loaded_pred = loaded_model.predict(X_test.iloc[[0]])
    print(f"Sample prediction successful: {loaded_pred[0]}")
    
    if "C" in loaded_model.classes_:
        raise RuntimeError("Model was trained with Bucket C! Invariant violation.")

if __name__ == "__main__":
    train_model()
