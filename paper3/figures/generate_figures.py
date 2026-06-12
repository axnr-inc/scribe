#!/usr/bin/env python3
"""Generate all paper figures for paper3.tex.

Five figures:
  fig1: Per-topic TB cross-family invariance (THE killer chart)
  fig2: CB cross-paradigm magnitude shift (DABStep 80pp vs RuleArena 27pp)
  fig3: Refuted mitigation triad bar chart
  fig4: TB/CB recovery signatures overlap (Venn-style)
  fig5: Phase decomposition framework (read/compute/commit)

Saves as PDF (vector) for IEEE column embedding.
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

OUT = Path(__file__).parent
plt.rcParams.update({
    'font.family': 'serif',
    'font.size': 9,
    'axes.labelsize': 9,
    'axes.titlesize': 10,
    'legend.fontsize': 8,
    'xtick.labelsize': 8,
    'ytick.labelsize': 8,
    'figure.dpi': 200,
})


# =====================================================================
# Figure 1: Per-topic TB cross-family invariance — THE killer chart
# =====================================================================
def fig1_tb_invariance():
    topics = ['aci_format', 'fee_rule', 'date_specific', 'delta_what_if']
    kimi_tb_pct = [100, 14, 57, 37]
    kimi_n = [16, 37, 23, 19]
    ds_tb_pct = [100, 14, 30, 14]
    ds_n = [3, 21, 10, 7]

    fig, ax = plt.subplots(figsize=(6.5, 3.2))
    x = np.arange(len(topics))
    width = 0.36

    bars1 = ax.bar(x - width/2, kimi_tb_pct, width, color='#3274A1', label=f'Kimi K2.6 (n shown above)', edgecolor='black', linewidth=0.5)
    bars2 = ax.bar(x + width/2, ds_tb_pct, width, color='#E1812C', label=f'DeepSeek V4 Pro', edgecolor='black', linewidth=0.5)

    # Label bars with n values
    for i, (n, p) in enumerate(zip(kimi_n, kimi_tb_pct)):
        ax.text(i - width/2, p + 2, f'n={n}', ha='center', fontsize=7)
    for i, (n, p) in enumerate(zip(ds_n, ds_tb_pct)):
        ax.text(i + width/2, p + 2, f'n={n}', ha='center', fontsize=7)

    # Mark exact-replication topics with arrows
    ax.annotate('Exact', xy=(0, 100), xytext=(0, 116),
                ha='center', fontsize=8, fontweight='bold', color='#2D4D2D',
                arrowprops=dict(arrowstyle='-', color='#2D4D2D', lw=0.8))
    ax.annotate('Exact', xy=(1, 14), xytext=(1, 28),
                ha='center', fontsize=8, fontweight='bold', color='#2D4D2D',
                arrowprops=dict(arrowstyle='-', color='#2D4D2D', lw=0.8))

    ax.set_xticks(x)
    ax.set_xticklabels(topics, rotation=0)
    ax.set_ylabel('TB rate within topic (%)')
    ax.set_title('Per-topic TB rate replicates exactly on the two dominant clusters')
    ax.set_ylim(0, 125)
    ax.legend(loc='upper right')
    ax.grid(axis='y', linestyle=':', alpha=0.5)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    plt.tight_layout()
    plt.savefig(OUT / 'fig1_tb_invariance.pdf', bbox_inches='tight')
    plt.savefig(OUT / 'fig1_tb_invariance.png', bbox_inches='tight')
    plt.close()
    print(f"  ✓ fig1_tb_invariance.pdf")


# =====================================================================
# Figure 2: CB cross-paradigm magnitude shift
# =====================================================================
def fig2_cb_paradigm():
    fig, ax = plt.subplots(figsize=(5.5, 3.3))

    paradigms = ['DABStep fee_rule\n(multi-turn agentic,\nwith Python REPL)',
                 'RuleArena NBA\n(single-turn,\nno tools)']
    opus_rates = [100, 30]
    kimi_rates = [20, 3]

    x = np.arange(len(paradigms))
    width = 0.32

    bars1 = ax.bar(x - width/2, opus_rates, width, color='#3274A1', label='Opus 4.6 (frontier)', edgecolor='black', linewidth=0.5)
    bars2 = ax.bar(x + width/2, kimi_rates, width, color='#E1812C', label='Kimi K2.6 (open)', edgecolor='black', linewidth=0.5)

    # Gap annotations
    gaps = [80, 27]
    for i, gap in enumerate(gaps):
        max_h = max(opus_rates[i], kimi_rates[i])
        # Bracket
        ax.annotate('', xy=(i + width/2, kimi_rates[i] + 2), xytext=(i + width/2, opus_rates[i] - 2),
                    arrowprops=dict(arrowstyle='<->', color='#C0392B', lw=1.5))
        ax.text(i + width/2 + 0.18, (opus_rates[i] + kimi_rates[i]) / 2,
                f'{gap}\nppts',
                ha='left', va='center', fontsize=9, fontweight='bold', color='#C0392B')

    ax.set_xticks(x)
    ax.set_xticklabels(paradigms, fontsize=8)
    ax.set_ylabel('Pass rate (%)')
    ax.set_title('CB gap exists across paradigms, magnitude differs by phase loading')
    ax.set_ylim(0, 130)
    ax.legend(loc='upper right', fontsize=8)
    ax.grid(axis='y', linestyle=':', alpha=0.5)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    plt.tight_layout()
    plt.savefig(OUT / 'fig2_cb_paradigm.pdf', bbox_inches='tight')
    plt.savefig(OUT / 'fig2_cb_paradigm.png', bbox_inches='tight')
    plt.close()
    print(f"  ✓ fig2_cb_paradigm.pdf")


# =====================================================================
# Figure 3: Refuted mitigation triad
# =====================================================================
def fig3_refutations():
    mitigations = [
        ('Baseline pass@1', 0, 10, '#A0A0A0'),
        ('Re-sampling pass@5', 20, 10, '#A0A0A0'),
        ('Majority vote\n(≥3 of 5)', 0, 10, '#A0A0A0'),
        ('SC modal vote', 0, 10, '#C0392B'),
        ('Prompt simplification', 0, 5, '#C0392B'),
        ('Reasoning amp\n(n=1 task)', 0, 1, '#C0392B'),
        ('Variant-B doc inject', 40, 5, '#C0392B'),
        ('Reflexion verbal\ncritique', 0, 10, '#C0392B'),
    ]
    labels = [m[0] for m in mitigations]
    rates = [m[1] for m in mitigations]
    ns = [m[2] for m in mitigations]
    colors = [m[3] for m in mitigations]

    fig, ax = plt.subplots(figsize=(7, 3.5))
    bars = ax.barh(range(len(mitigations)), rates, color=colors, edgecolor='black', linewidth=0.5)

    for i, (lbl, r, n) in enumerate(zip(labels, rates, ns)):
        if r == 0:
            ax.text(2, i, f'0/{n} (refuted)', va='center', fontsize=8, color='#C0392B', fontweight='bold')
        else:
            ax.text(r + 2, i, f'{r}% (n={n})', va='center', fontsize=8)

    # Add a reference vertical line for Opus baseline 100%
    ax.axvline(100, color='#2D4D2D', linestyle='--', linewidth=1, alpha=0.7)
    ax.text(102, len(mitigations) - 0.5, 'Opus 4.6 baseline\non same cluster',
            fontsize=7, va='center', color='#2D4D2D')

    ax.set_yticks(range(len(mitigations)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel('Pass rate on fee_rule iter-capped cluster (%)')
    ax.set_title('Six mitigations against the CB gap, all fail to bridge it')
    ax.set_xlim(0, 110)
    ax.invert_yaxis()
    ax.grid(axis='x', linestyle=':', alpha=0.5)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    plt.tight_layout()
    plt.savefig(OUT / 'fig3_refutations.pdf', bbox_inches='tight')
    plt.savefig(OUT / 'fig3_refutations.png', bbox_inches='tight')
    plt.close()
    print(f"  ✓ fig3_refutations.pdf")


# =====================================================================
# Figure 4: TB/CB recovery signatures overlap (matplotlib Venn-like)
# =====================================================================
def fig4_overlap():
    fig, ax = plt.subplots(figsize=(5.5, 3.5))
    from matplotlib.patches import Rectangle

    # Boxes sized to fit cleanly with caption row at bottom
    tb_box = Rectangle((0.05, 0.40), 0.42, 0.40,
                       facecolor='#3274A1', alpha=0.4, edgecolor='black', linewidth=1)
    cb_box = Rectangle((0.36, 0.25), 0.56, 0.55,
                       facecolor='#E1812C', alpha=0.4, edgecolor='black', linewidth=1)
    eb_box = Rectangle((0.04, 0.08), 0.89, 0.09,
                       facecolor='#9B59B6', alpha=0.3, edgecolor='black', linewidth=1)
    ax.add_patch(tb_box)
    ax.add_patch(cb_box)
    ax.add_patch(eb_box)

    # TB labels (inside TB-only region)
    ax.text(0.18, 0.72, 'TB', fontsize=14, fontweight='bold', ha='center')
    ax.text(0.18, 0.66, '(termination-bound)', fontsize=7, ha='center', style='italic')
    ax.text(0.18, 0.55, 'TB only:\n3 tasks', fontsize=9, ha='center')

    # CB labels (inside CB-only region)
    ax.text(0.78, 0.70, 'CB', fontsize=14, fontweight='bold', ha='center')
    ax.text(0.78, 0.64, '(capability-bound)', fontsize=7, ha='center', style='italic')
    ax.text(0.78, 0.40, 'CB only:\n79 tasks', fontsize=9, ha='center')

    # Overlap label
    ax.text(0.415, 0.62, 'TB$\\cap$CB', fontsize=10, fontweight='bold', ha='center')
    ax.text(0.415, 0.56, '10 tasks', fontsize=9, ha='center')

    # EB row label (centered in purple bar)
    ax.text(0.5, 0.125, 'EB-potential (Kimi-incorrect class): 93 tasks',
            fontsize=8, ha='center', fontweight='bold')

    # Caption: DeepSeek recovered count (single centered line at top, with breathing room)
    ax.text(0.5, 0.93, 'DeepSeek recovered: 8 of 190 stratified Kimi failures',
            fontsize=8, ha='center', style='italic', color='#2D4D2D')

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect('auto')
    ax.axis('off')
    ax.set_title('Recovery signatures overlap; mechanisms are not disjoint', pad=12)

    plt.tight_layout()
    plt.savefig(OUT / 'fig4_overlap.pdf', bbox_inches='tight')
    plt.savefig(OUT / 'fig4_overlap.png', bbox_inches='tight')
    plt.close()
    print(f"  ✓ fig4_overlap.pdf")


# =====================================================================
# Figure 5: Phase decomposition diagram
# =====================================================================
def fig5_phases():
    fig, ax = plt.subplots(figsize=(7, 2.7))

    from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

    phases = [
        ('Read \\& Extract', 'parse docs\nderive rules', '#5DADE2', 'EB\n(extraction-bound)'),
        ('Compute \\& Apply', 'execute computation\nusing extracted rules', '#F39C12', 'CB\n(capability-bound)'),
        ('Commit \\& Emit', 'decide done,\nemit answer', '#58D68D', 'TB\n(termination-bound)'),
    ]

    box_w = 0.22
    box_h = 0.45
    gap = 0.10
    start_x = 0.05

    for i, (name, desc, color, mech) in enumerate(phases):
        x = start_x + i * (box_w + gap)
        # Phase box
        box = FancyBboxPatch((x, 0.45), box_w, box_h,
                             boxstyle='round,pad=0.01',
                             facecolor=color, alpha=0.6,
                             edgecolor='black', linewidth=1)
        ax.add_patch(box)
        ax.text(x + box_w/2, 0.78, f'Phase {i+1}', fontsize=9, fontweight='bold', ha='center')
        ax.text(x + box_w/2, 0.71, name, fontsize=8.5, ha='center', fontweight='bold')
        ax.text(x + box_w/2, 0.58, desc, fontsize=7.5, ha='center')

        # Failure mode below
        ax.text(x + box_w/2, 0.35, '↓ failure type', fontsize=7, ha='center', color='#555')
        ax.text(x + box_w/2, 0.22, mech, fontsize=9, ha='center', fontweight='bold', color='#C0392B')

        # Arrow to next phase
        if i < len(phases) - 1:
            ax.annotate('', xy=(x + box_w + gap - 0.005, 0.675), xytext=(x + box_w + 0.005, 0.675),
                        arrowprops=dict(arrowstyle='->', color='black', lw=1.5))

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    ax.set_title('Phase decomposition: failure-mechanism load determined by task structure', fontsize=10)

    plt.tight_layout()
    plt.savefig(OUT / 'fig5_phases.pdf', bbox_inches='tight')
    plt.savefig(OUT / 'fig5_phases.png', bbox_inches='tight')
    plt.close()
    print(f"  ✓ fig5_phases.pdf")


if __name__ == '__main__':
    print("Generating paper figures...")
    fig1_tb_invariance()
    fig2_cb_paradigm()
    fig3_refutations()
    fig4_overlap()
    fig5_phases()
    print("Done.")
