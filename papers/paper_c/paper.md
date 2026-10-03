---
id: paper_c
title: Tuning Matters: Classical Models on Imbalanced and High-Dimensional Data
authors: Demo Authors (fictional)
venue: Fictional demo paper built to test Preflight. Not a real publication.
repo: papers/paper_c/repo
---

## Abstract

We study classical models on four synthetic benchmarks. Logistic regression reaches 90.97 macro-F1 on the imbalanced SynthMed task, a tuned RBF SVM beats logistic regression on the high-dimensional SynthHD task, and 1-NN reaches 90.60% on SynthKNN-Aug.

## 1 Experimental protocol

All results are averaged over 10 random seeds (seeds 0 to 9) with a stratified 75/25 train/test split. Features are standardised where stated.

## 2 Experiments

### 2.1 SynthMed

SynthMed is imbalanced, with 15% positives, so we report macro-F1. Logistic regression uses C = 1.0 and max_iter = 1000 on standardised features.

### 2.2 SynthHD

SynthHD has 500 samples and 150 features. The SVM is tuned over C and gamma by 3-fold cross-validation. The logistic regression baseline uses C = 1.0 and max_iter = 2000.

### 2.3 SynthKNN-Aug

The 1-NN classifier uses n_neighbors = 1 on standardised features. The data pool is enlarged by re-sampling 40% of the samples.

### 2.4 SynthLarge-2M

Logistic regression uses C = 1.0 and max_iter = 1000 on 2,000,000 samples with 40 features.

## 3 Results

Table 1: Macro-F1 (%) on SynthMed.

| Method | SynthMed macro-F1 (%) |
|---|---|
| Logistic Regression | 90.97 |

Table 2: Test accuracy (%) on SynthHD.

| Method | SynthHD acc. (%) |
|---|---|
| SVM (RBF, tuned) | 86.64 |
| Logistic Regression | 85.12 |

The tuned SVM (RBF) consistently outperforms logistic regression on SynthHD, by 1.52 points.

Table 3: Test accuracy (%) on SynthKNN-Aug.

| Method | SynthKNN-Aug acc. (%) |
|---|---|
| 1-NN | 90.60 |

Table 4: Test accuracy (%) on SynthLarge-2M.

| Method | SynthLarge-2M acc. (%) |
|---|---|
| Logistic Regression | 81.08 |
