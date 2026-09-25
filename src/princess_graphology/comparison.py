from __future__ import annotations
import numpy as np

def z_scores(x, mean, std, eps=1e-9):
    return (np.asarray(x, float) - np.asarray(mean, float)) / np.maximum(np.asarray(std, float), eps)

def cosine_similarity(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return 0.0 if denominator == 0 else float(np.dot(a, b) / denominator)

def euclidean_distance(a, b):
    return float(np.linalg.norm(np.asarray(a, float) - np.asarray(b, float)))

def mahalanobis_distance(x, mean, covariance, regularization=1e-6):
    """Actual Mahalanobis distance with regularized covariance."""
    x, mean, cov = np.asarray(x, float), np.asarray(mean, float), np.asarray(covariance, float)
    if cov.ndim != 2 or cov.shape[0] != cov.shape[1]:
        raise ValueError("covariance must be square")
    regularized = cov + np.eye(cov.shape[0]) * regularization
    delta = x - mean
    inverse = np.linalg.pinv(regularized)
    return float(np.sqrt(max(0.0, delta @ inverse @ delta)))

def baseline_profile(samples):
    a = np.asarray(samples, float)
    if a.ndim != 2 or a.shape[0] < 2:
        raise ValueError("need >=2 equal-length sample vectors")
    return {"mean": a.mean(axis=0), "std": a.std(axis=0, ddof=1), "covariance": np.cov(a, rowvar=False), "n": a.shape[0]}
