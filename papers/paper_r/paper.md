---
id: paper_r
title: Nuclear Feature Extraction for Breast Tumor Diagnosis (case study)
authors: W. N. Street, W. H. Wolberg, O. L. Mangasarian. IS&T/SPIE 1993, vol. 1905, pp. 861-870
venue: Real paper. Claims summarised from the authors' published dataset record (UCI WDBC, 1995). The paper released no code, so the repo holds reproduction code written for this case study.
repo: papers/paper_r/repo
---

## Abstract

Thirty nuclear features are computed from digitised fine-needle aspirates of breast masses. A single separating plane in the 3-D space of worst area, worst smoothness and mean texture gives the best predictive accuracy, estimated at 97.50% with repeated 10-fold cross-validation. The two classes are linearly separable using all 30 input features.

## 1 Experimental protocol

Breast Cancer accuracy is estimated with repeated 10-fold cross-validation on the 569 diagnosed cases.

## 2 Methods

### 2.1 Separating plane with 3 features

A single separating plane is fitted in the 3-D space of worst area, worst smoothness and mean texture. Relevant features were selected using an exhaustive search in the space of 1-4 features and 1-3 separating planes.

### 2.2 Separating plane with 30 features

Using all 30 input features, the benign and malignant sets are linearly separable.

## 3 Results

Table 1: Accuracy (%) on Breast Cancer.

| Method | Breast Cancer acc. (%) |
|---|---|
| Separating plane (3 features, repeated 10-fold CV) | 97.50 |
| Separating plane (30 features, training set) | 100.00 |
