import os
import joblib
from pydantic import BaseModel
from typing import Dict
from app.schemas.payment import PaymentEvent
from app.services.ml_features import extract_single_feature

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "models", "recovery_classifier.joblib")

class MLClassificationResult(BaseModel):
    predicted_bucket: str
    confidence: float
    probabilities: Dict[str, float]

class ModelNotLoadedError(Exception):
    """Exception raised when the ML model cannot be loaded."""
    pass

def _load_model():
    if not os.path.exists(MODEL_PATH):
        raise ModelNotLoadedError(f"ML model is unavailable at {MODEL_PATH}. Train the model before using ML classification.")
    try:
        return joblib.load(MODEL_PATH)
    except Exception as e:
        raise ModelNotLoadedError(f"Failed to load ML model: {str(e)}")

def predict(event: PaymentEvent) -> MLClassificationResult:
    """
    Predicts the Bucket (A or B) for a given PaymentEvent.
    Raises RuntimeError if the model outputs 'C'.
    """
    model = _load_model()
    
    # 1. Extract features using the shared pipeline
    features_df = extract_single_feature(event)
    
    # 2. Predict probabilities
    # Classes are typically ['A', 'B'] but could be ordered differently.
    classes = model.classes_
    proba = model.predict_proba(features_df)[0]
    
    prob_dict = {str(c): float(p) for c, p in zip(classes, proba)}
    
    # 3. Determine the predicted class (max probability)
    predicted_class = model.predict(features_df)[0]
    confidence = prob_dict[predicted_class]
    
    # 4. Enforce strict Bucket C invariant
    if predicted_class == "C" or "C" in classes:
        raise RuntimeError(
            "ML classifier predicted Bucket C (or was trained on it). "
            "Bucket C must only originate from the deterministic regulatory engine."
        )
    
    return MLClassificationResult(
        predicted_bucket=predicted_class,
        confidence=confidence,
        probabilities=prob_dict
    )

def is_confident(confidence: float) -> bool:
    """
    Returns True if the ML model's confidence is >= 0.75 exactly.
    """
    return confidence >= 0.75

