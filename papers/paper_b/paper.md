---
id: paper_b
title: Classical Baselines on Handwritten Digits
authors: Demo Authors (fictional)
venue: Fictional demo paper built to test Preflight. Not a real publication. Clean control.
repo: papers/paper_b/repo
---

## Abstract

We report two classical baselines on the Digits dataset. k-NN reaches 97.67% and logistic regression reaches 97.00% test accuracy.

## 1 Experimental protocol

All results are test accuracy (%) on a stratified 80/20 train/test split, averaged over 5 random seeds (seeds 0 to 4). Features are standardised with a StandardScaler fitted on the training split inside a Pipeline.

## 2 Models

### 2.1 k-NN

The k-NN classifier uses n_neighbors = 3.

### 2.2 Logistic Regression

Logistic regression uses C = 1.0 and max_iter = 2000.

## 3 Results

Table 1: Test accuracy (%) on Digits.

| Method | Digits acc. (%) |
|---|---|
| k-NN | 97.67 |
| Logistic Regression | 97.00 |
