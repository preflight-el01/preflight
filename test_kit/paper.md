---
id: paper_t
title: Three Baselines for Tumour Classification
authors: Test Authors (fictional)
venue: Fictional test paper for checking Preflight. Not a real publication.
---

## Abstract

We report three classical baselines on the Breast Cancer dataset. Logistic regression reaches 97.06%, an SVM reaches 96.50% and a decision tree reaches 93.43% test accuracy.

## 1 Experimental protocol

All results are test accuracy (%) on a stratified 75/25 train/test split, averaged over 5 random seeds (seeds 0 to 4). Features are standardised with a StandardScaler fitted on the training split only.

## 2 Models

### 2.1 Decision Tree

The decision tree uses max_depth = 4.

### 2.2 Logistic Regression

Logistic regression uses C = 1.0 and max_iter = 5000.

### 2.3 SVM

The SVM uses an RBF kernel with C = 1.0.

## 3 Results

Table 1: Test accuracy (%) on Breast Cancer.

| Method | Breast Cancer acc. (%) |
|---|---|
| Decision Tree | 93.43 |
| Logistic Regression | 97.06 |
| SVM | 96.50 |
