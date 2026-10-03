"""Write papers/paper_c/paper.pdf: fictional Paper C as an ordinary two-page paper (prose and real
tables, not Preflight's Markdown), so the AI paper reader can be tried without finding a PDF."""
import os

from fpdf import FPDF

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TITLE = "Tuning Matters: Classical Models on Imbalanced and High-Dimensional Data"
BODY = [
    ("Abstract", [
        "Classical models remain strong baselines on tabular data, provided they are tuned. We study logistic "
        "regression, a tuned RBF support vector machine and nearest-neighbour classification on four synthetic "
        "benchmarks that mimic common failure modes of real data: class imbalance, many features with few "
        "samples, and very large sample sizes."]),
    ("1  Experimental protocol", [
        "Every number in this paper is the mean of 10 runs with random seeds 0 to 9. Each run draws a stratified "
        "75/25 train/test split. Features are standardised where stated."]),
    ("2  Experiments", [
        "SynthMed is an imbalanced diagnosis-style task with 15% positives, so we report macro-averaged F1. "
        "Logistic regression is regularised with C = 1.0 and trained for at most 1000 iterations on "
        "standardised features.",
        "SynthHD has 500 samples and 150 features. The SVM is tuned over C and gamma by 3-fold cross-validation. "
        "The logistic regression baseline uses C = 1.0 and up to 2000 iterations.",
        "On SynthKNN-Aug we use a 1-nearest-neighbour classifier on standardised features. The data pool is "
        "enlarged by re-sampling 40% of the samples.",
        "SynthLarge-2M has 2,000,000 samples with 40 features; logistic regression uses C = 1.0 and at most "
        "1000 iterations."]),
]
TABLES = [
    ("Table 1. Macro-F1 (%) on SynthMed.", ["Method", "SynthMed macro-F1"], [["Logistic regression", "90.97"]]),
    ("Table 2. Test accuracy (%) on SynthHD.", ["Method", "SynthHD accuracy"],
     [["SVM (RBF, tuned)", "86.64"], ["Logistic regression", "85.12"]]),
    ("Table 3. Test accuracy (%) on SynthKNN-Aug and SynthLarge-2M.", ["Method", "SynthKNN-Aug", "SynthLarge-2M"],
     [["1-NN", "90.60", ""], ["Logistic regression", "", "81.08"]]),
]
DISCUSSION = ("The tuned SVM consistently outperforms logistic regression on SynthHD, by 1.52 points. "
              "Nearest neighbours profit from the enlarged data pool, and logistic regression scales to two "
              "million samples without loss of accuracy.")


def main():
    pdf = FPDF(format="A4")
    pdf.set_margins(22, 20, 22)
    pdf.add_page()
    pdf.set_font("Times", "B", 16)
    pdf.multi_cell(0, 8, TITLE, align="C")
    pdf.set_font("Times", "I", 11)
    pdf.cell(0, 7, "Demo Authors (fictional)", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Times", "", 9)
    pdf.cell(0, 6, "Fictional paper written to test Preflight. Not a real publication.", align="C",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    for head, paras in BODY:
        pdf.set_font("Times", "B", 12)
        pdf.cell(0, 8, head, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Times", "", 11)
        for p in paras:
            pdf.multi_cell(0, 5.6, p)
            pdf.ln(2)
    pdf.set_font("Times", "B", 12)
    pdf.cell(0, 8, "3  Results", new_x="LMARGIN", new_y="NEXT")
    for cap, head, rows in TABLES:
        pdf.set_font("Times", "", 10)
        pdf.cell(0, 7, cap, new_x="LMARGIN", new_y="NEXT")
        widths = [70] + [40] * (len(head) - 1)
        pdf.set_font("Times", "B", 10)
        for w, h in zip(widths, head):
            pdf.cell(w, 6, h, border="TB")
        pdf.ln()
        pdf.set_font("Times", "", 10)
        for r in rows:
            for w, v in zip(widths, r):
                pdf.cell(w, 6, v, align="L" if w == 70 else "R")
            pdf.ln()
        pdf.cell(sum(widths), 0, "", border="T", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)
    pdf.set_font("Times", "", 11)
    pdf.multi_cell(0, 5.6, DISCUSSION)
    out = os.path.join(ROOT, "papers", "paper_c", "paper.pdf")
    pdf.output(out)
    print("wrote", out, os.path.getsize(out), "bytes")


if __name__ == "__main__":
    main()
