import argparse
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import font_manager
import seaborn as sns
import pymc as pm

plt.style.use('seaborn-v0_8-whitegrid')
sns.set_palette("husl")

def norm_cdf_2(x, mean, slope, lapse_rate):
    return lapse_rate + (1 - 2 * lapse_rate) * pm.math.invprobit((x - mean) / slope)

def plot_jitter(size, seed=42):
    return np.random.default_rng(seed).normal(0, 0.05, size)


def plot_average_psychometric_curves(csv_file="subject_parameters.csv", seed=42,
                                   output="average_psychometric_curves.pdf"):
    font_dir = Path(__file__).resolve().parent / 'fonts'
    fonts = [font_dir / name for name in ['Lato-Regular.ttf', 'Lato-Bold.ttf']]
    for font in fonts:
        font_manager.fontManager.addfont(font)
    plt.rcParams.update({'font.family': 'Lato', 'pdf.fonttype': 42, 'ps.fonttype': 42})
    df = pd.read_csv(csv_file)

    mean_single_avg = df["Mean Single"].mean()
    slope_single_avg = df["Slope Single"].mean()
    mean_multi_avg = df["Mean Multi"].mean()
    slope_multi_avg = df["Slope Multi"].mean()
    lapse_rate_avg = df["Lapse Rate"].mean()

    # Mass ratio relative to the reference.
    intensity_range = np.logspace(np.log10(0.25), np.log10(4.0), 300)
    transformed_intensities = np.log(intensity_range)

    norm_cdf_single = norm_cdf_2(transformed_intensities,
                                 mean_single_avg, slope_single_avg, lapse_rate_avg).eval()
    norm_cdf_multi  = norm_cdf_2(transformed_intensities,
                                 mean_multi_avg,  slope_multi_avg,  lapse_rate_avg).eval()

    fig, axs = plt.subplots(1, 2, figsize=(7, 5), gridspec_kw={'width_ratios': [3, 2]})
    ax1, ax2 = axs

    for _, row in df.iterrows():
        ax1.plot(intensity_range,
                 norm_cdf_2(np.log(intensity_range),
                            row["Mean Single"], row["Slope Single"], row["Lapse Rate"]).eval(),
                 color="#4285F4", alpha=0.1, linewidth=1.0, linestyle='--')
        ax1.plot(intensity_range,
                 norm_cdf_2(np.log(intensity_range),
                            row["Mean Multi"], row["Slope Multi"], row["Lapse Rate"]).eval(),
                 color="#DB4437", alpha=0.1, linewidth=1.0, linestyle='--')

    ax1.plot(intensity_range, norm_cdf_single, label="Single",
             color="#4285F4", linewidth=3.0)
    ax1.plot(intensity_range, norm_cdf_multi,   label="Ensemble",
             color="#DB4437", linewidth=3.0)

    ax1.set_xscale('log')
    ax1.set_xticks([0.25, 0.5, 1, 2, 4])
    ax1.set_xticklabels(["1/4", "1/2", "1", "2", "4"])
    ax1.set_xlim(0.25, 4)
    ax1.set_ylim(0, 1)
    ax1.set_xlabel('Mass Ratio', fontsize=14, labelpad=10, color='#444')
    ax1.set_ylabel('Probability of "Heavier" Response', fontsize=14, labelpad=10, color='#444')
    ax1.set_title('A) Psychometric Curves', fontsize=16, pad=20, fontweight='bold', color='#444')

    y_ticks = np.arange(0.1, 1.1, 0.1)
    ax1.set_yticks(y_ticks)
    for y_tick in np.arange(0.05, 1.05, 0.1):
        ax1.axhline(y=y_tick, color='lightgray', linestyle='--', linewidth=0.5)

    ax1.legend(frameon=True, fancybox=True, shadow=True, fontsize=12)

    # Participant widths.
    single_sds   = df["Slope Single"].tolist()
    ensemble_sds = df["Slope Multi"].tolist()
    single_mean  = np.mean(single_sds)
    multi_mean   = np.mean(ensemble_sds)

    ax2.bar(0, single_mean, color='#A4C2F4')
    ax2.bar(1, multi_mean,  color='#F4B5B0')

    jitter = plot_jitter(len(single_sds), seed)
    for i in range(len(single_sds)):
        ax2.plot([0 + jitter[i], 1 + jitter[i]],
                 [single_sds[i], ensemble_sds[i]],
                 color='#888', linewidth=0.8, alpha=0.4)
        ax2.scatter([0 + jitter[i]], [single_sds[i]],
                    color='#4285F4', s=10, alpha=0.5)
        ax2.scatter([1 + jitter[i]], [ensemble_sds[i]],
                    color='#DB4437', s=10, alpha=0.5)

    ax2.set_xlim(-0.5, 1.5)
    ax2.set_ylim(bottom=0)
    ax2.set_xticks([0, 1])
    ax2.set_xticklabels(['Single', 'Ensemble'], fontsize=14)
    ax2.set_ylabel(r'Width ($S$)', fontsize=14, labelpad=10, color='#444', math_fontfamily='cm')
    ax2.set_title('B) Curve Width', fontsize=16, pad=20, fontweight='bold', color='#444')

    plt.tight_layout()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output, metadata={'CreationDate':None,'ModDate':None})
    plt.savefig(output.with_suffix('.png'), dpi=180)
    plt.close(fig)

if __name__ == "__main__":
    parser=argparse.ArgumentParser(description="Plot saved Experiment 1 estimates")
    parser.add_argument("--seed",type=int,default=42)
    parser.add_argument("--csv",type=Path,default=Path('subject_parameters.csv'))
    parser.add_argument("--out",type=Path,default=Path('average_psychometric_curves.pdf'))
    args=parser.parse_args()
    if args.seed < 0:
        parser.error('seed must be nonnegative')
    plot_average_psychometric_curves(args.csv,args.seed,args.out)
