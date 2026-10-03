---
id: paper_a
title: Small Models, Strong Baselines: A Study of Classical Classifiers on Tabular Benchmarks
authors: Demo Authors (fictional)
venue: Fictional demo paper built to test Preflight. Not a real publication.
repo: papers/paper_a/repo
---

## Abstract

We revisit classical classifiers on small tabular benchmarks. Logistic regression reaches 98.25% accuracy on Breast Cancer, and an RBF SVM significantly outperforms k-NN on the same task. On the SynthGene-2k gene-expression benchmark, ANOVA feature selection with logistic regression reaches 92.40% accuracy.

## 1 Experimental protocol

All Breast Cancer results are test accuracy (%) on a stratified held-out split, averaged over 5 random seeds. Features are standardised with a StandardScaler fitted on the training split.

## 2 Models

### 2.1 Logistic Regression

We use L2-regularised logistic regression with inverse regularisation strength C = 1.0 and max_iter = 1000 using the lbfgs solver.

### 2.2 Decision Tree

The decision tree baseline uses max_depth = 4 with the Gini criterion.

### 2.3 SVM and k-NN

The SVM uses an RBF kernel with C = 1.0 and gamma = scale. The k-NN baseline uses n_neighbors = 5 with Euclidean distance.

### 2.4 SynthGene-2k

SynthGene-2k has 100 samples and 2,000 features, of which only a handful are informative. We select the top k = 20 features by ANOVA F-score and train logistic regression. We hold out 25% of samples for testing and report the mean over 10 random seeds.

### 2.5 ViT-B/16

We fine-tune a ViT-B/16 on ImageNet-1k for 30 epochs on 8 GPUs.

## 3 Results

Table 1: Test accuracy (%) on Breast Cancer.

| Method | Breast Cancer acc. (%) |
|---|---|
| Logistic Regression | 98.25 |
| Decision Tree | 93.86 |
| SVM (RBF) | 98.25 |
| k-NN | 95.61 |

The SVM (RBF) significantly outperforms k-NN on Breast Cancer, by 2.64 points.

Table 2: Test accuracy (%) on SynthGene-2k.

| Method | SynthGene-2k acc. (%) |
|---|---|
| ANOVA top-20 + Logistic Regression | 92.40 |

Table 3: Top-1 accuracy (%) on ImageNet-1k.

| Method | ImageNet-1k top-1 (%) |
|---|---|
| ViT-B/16 | 81.30 |
