"""Experiment 1 psychometric model; smaller curve widths indicate greater precision."""
import json
import pymc as pm
import numpy as np
import pytensor.tensor as pt

RANDOM_SEED = 42

def load_and_process_data(file_path='data.json'):
    """Keep noncatch responses and express mass relative to the reference (8)."""
    with open(file_path, 'r') as file:
        data = json.load(file)

    processed_data = []
    for subject in data:
        subject_data = {"single": [], "multi": []}
        for trial_type in ["single", "multi"]:
            if trial_type in subject:
                for trial_key, trial_info in subject[trial_type].items():
                    if trial_key != "fit_details" and not trial_key.startswith("catch"):
                        mass = trial_info["mass"] / 8
                        prediction = 1 if trial_info["prediction"] == "Heavier" else 0
                        subject_data[trial_type].append((mass, prediction))
        processed_data.append(subject_data)

    return processed_data

def norm_cdf_2(x, mean, slope, lapse_rate):
    """Heavier-response probability; slope is curve width (SD), lapse_rate is half the guessing rate."""
    return lapse_rate + (1 - 2 * lapse_rate) * pm.math.invprobit((x - mean) / slope)

def build_model(data, *, efficient=True):
    """Cumulative-Gaussian psychometric model with participant and population effects."""
    n_subjects = len(data)

    # Single-marble responses, indexed by participant.
    x1_list, y1_list, idx1_list = [], [], []
    for i, subj in enumerate(data):
        for mass, pred in subj['single']:
            x1_list.append(np.log(mass))
            y1_list.append(pred)
            idx1_list.append(i)
    x1 = np.array(x1_list)
    y1 = np.array(y1_list)
    idx1 = np.array(idx1_list)

    # Ensemble responses, using the same participant order.
    x2_list, y2_list, idx2_list = [], [], []
    for i, subj in enumerate(data):
        for mass, pred in subj['multi']:
            x2_list.append(np.log(mass))
            y2_list.append(pred)
            idx2_list.append(i)
    x2 = np.array(x2_list)
    y2 = np.array(y2_list)
    idx2 = np.array(idx2_list)

    def aggregate(x, y, idx):
        cells, inverse = np.unique(np.column_stack([idx, x]), axis=0, return_inverse=True)
        return (cells[:, 1], np.bincount(inverse, weights=y).astype(int),
                cells[:, 0].astype(int), np.bincount(inverse))

    # Pool repeated mass ratios within participants into binomial counts.
    if efficient:
        x1, y1, idx1, n1 = aggregate(x1, y1, idx1)
        x2, y2, idx2, n2 = aggregate(x2, y2, idx2)

    with pm.Model() as model:
        # Hyperpriors
        mu_mean = pm.Normal('mu_mean', 0, 25)
        sigma_mean = pm.HalfCauchy('sigma_mean', 25)

        mu_log_slope = pm.Normal('mu_log_slope', 0, 25)
        sigma_log_slope = pm.HalfCauchy('sigma_log_slope', 25)

        mu_diff_mean = pm.Normal('mu_diff_mean', 0, 25)
        sigma_diff_mean = pm.HalfCauchy('sigma_diff_mean', 25)

        mu_diff_log_slope = pm.Normal('mu_diff_log_slope', 0, 25)
        sigma_diff_log_slope = pm.HalfCauchy('sigma_diff_log_slope', 25)

        # Non-centered subject effects
        z_mean = pm.Normal('z_mean_single', 0, 1, shape=n_subjects)
        z_log_slope = pm.Normal('z_log_slope_single', 0, 1, shape=n_subjects)
        z_diff_m = pm.Normal('z_diff_mean', 0, 1, shape=n_subjects)
        z_diff_log_s = pm.Normal('z_diff_log_slope', 0, 1, shape=n_subjects)

        mean_single = pm.Deterministic('mean_single', mu_mean + sigma_mean * z_mean)

        log_slope_single = mu_log_slope + sigma_log_slope * z_log_slope
        slope_single = pm.Deterministic('slope_single', pm.math.exp(log_slope_single))

        diff_mean = mu_diff_mean + sigma_diff_mean * z_diff_m
        diff_log_slope = mu_diff_log_slope + sigma_diff_log_slope * z_diff_log_s
        slope_multi = pm.Deterministic('slope_multi', slope_single * pm.math.exp(diff_log_slope))

        mean_multi = pm.Deterministic('mean_multi', mean_single + diff_mean)

        # Hierarchical lapse rate (shared for single and multi)
        mu_lapse = pm.Beta('mu_lapse', alpha=2, beta=8)
        kappa_lapse = pm.Gamma('kappa_lapse', alpha=1, beta=1)
        
        # Guessing contributes equally to heavier and lighter responses.
        a = mu_lapse * kappa_lapse
        b = (1 - mu_lapse) * kappa_lapse
        if efficient:
            # If x ~ Beta(a,b) and w = -a*log(x), then
            # p(w) = exp(-w)*(1-exp(-w/a))**(b-1)/(a*B(a,b)).
            # The Exponential base density plus this correction is exact.
            w = pm.Exponential('lapse_scaled_log', 1, shape=n_subjects)
            log_x = -w / a
            lapse_rate_raw = pm.Deterministic('lapse_rate_raw', pt.exp(log_x))
            log_beta = pt.gammaln(a) + pt.gammaln(b) - pt.gammaln(a + b)
            pm.Potential('lapse_prior_correction', pt.sum(
                (b - 1) * pt.log1mexp(log_x) - pt.log(a) - log_beta))
        else:
            lapse_rate_raw = pm.Beta('lapse_rate_raw', alpha=a, beta=b, shape=n_subjects)
        lapse_rate = pm.Deterministic('lapse_rate', 0.5 * lapse_rate_raw)


        # Single-marble likelihood.
        p1 = norm_cdf_2(
            x1,
            mean_single[idx1],
            slope_single[idx1],
            lapse_rate[idx1]
        )
        if efficient:
            pm.Binomial("obs_single", n=n1, p=p1, observed=y1)
        else:
            pm.Bernoulli("obs_single", p=p1, observed=y1)

        # Ensemble likelihood.
        p2 = norm_cdf_2(
            x2,
            mean_multi[idx2],
            slope_multi[idx2],
            lapse_rate[idx2]
        )
        if efficient:
            pm.Binomial("obs_multi", n=n2, p=p2, observed=y2)
        else:
            pm.Bernoulli("obs_multi", p=p2, observed=y2)

    return model


def infer_hierarchical_psychometric_function(data, seed=RANDOM_SEED, *,
                                           draws=15000, tune=4000, cores=4,
                                           target_accept=.99, efficient=True):
    """Sample four chains using separate random streams from the supplied seed."""
    if draws < 1 or tune < 1 or cores < 1 or not 0 < target_accept < 1:
        raise ValueError("Invalid sampling settings")
    with build_model(data, efficient=efficient):

        trace = pm.sample(
            draws=draws,
            tune=tune,
            return_inferencedata=True,
            init='adapt_diag',
            random_seed=seed,
            chains=4, cores=min(cores, 4), target_accept=target_accept,
        )

    return trace

