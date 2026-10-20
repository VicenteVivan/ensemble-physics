"""Posterior summaries and participant estimates for Experiment 1."""
import json
from pathlib import Path

import arviz as az
import numpy as np
import pandas as pd
import xarray as xr


def participant_array(posterior, name):
    array = posterior[name]
    dims = [d for d in array.dims if d not in ('chain', 'draw')]
    if len(dims) != 1:
        raise ValueError(f'{name}: expected one participant dimension')
    return array.rename({dims[0]: 'subject'}).transpose('chain', 'draw', 'subject')


def diagnostics(trace):
    table = az.summary(trace, kind='diagnostics', round_to='none')
    result = dict(divergences=int(trace.sample_stats.diverging.sum()),
                  max_rhat=float(table.r_hat.max()),
                  min_ess_bulk=float(table.ess_bulk.min()),
                  min_ess_tail=float(table.ess_tail.min()))
    result['passed'] = (result['divergences'] == 0 and result['max_rhat'] <= 1.01
                        and min(result['min_ess_bulk'], result['min_ess_tail']) >= 400)
    return result


def summarize(trace, data, out):
    out = Path(out)
    posterior = trace.posterior
    ids = [p['PROLIFIC_PID'] for p in data]
    if json.loads(posterior.attrs['participant_ids']) != ids:
        raise ValueError('Posterior participant order differs from the data')
    names = ['mean_single', 'mean_multi', 'slope_single', 'slope_multi', 'lapse_rate']
    # Align participant axes before computing paired differences.
    arrays = xr.align(*(participant_array(posterior, name) for name in names), join='exact')
    mean_single, mean_multi, width_single, width_multi, lapse = arrays
    mean_diff, width_diff = mean_multi - mean_single, width_multi - width_single
    rows = []
    for i in range(len(ids)):
        avg = lambda a: a.isel(subject=i).mean(('chain', 'draw')).item()
        rows.append({'Subject': i + 1, 'Mean Single': avg(mean_single),
                     'Mean Multi': avg(mean_multi), 'Mean Difference': avg(mean_diff),
                     'Slope Single': avg(width_single), 'Slope Multi': avg(width_multi),
                     'Slope Difference': avg(width_diff), 'Lapse Rate': avg(lapse)})
    pd.DataFrame(rows).to_csv(out / 'participant_estimates.csv', index=False)
    single, multi = width_single.values, width_multi.values
    single_mean, multi_mean = single.mean(-1), multi.mean(-1)
    # Compute each contrast per draw, then summarize its posterior distribution.
    draws = {
        'mean_single_width': single_mean,
        'mean_ensemble_width': multi_mean,
        'mean_width_difference': multi_mean - single_mean,
        'ratio_of_mean_widths': multi_mean / single_mean,
        'percent_narrower': 100 * (1 - multi_mean / single_mean),
        'mean_participant_width_ratio': (multi / single).mean(-1),
        'population_median_width_ratio': np.exp(posterior.mu_diff_log_slope.values),
        'population_log_width_ratio_sd': posterior.sigma_diff_log_slope.values,
        'population_threshold_difference': posterior.mu_diff_mean.values,
        'population_single_threshold': posterior.mu_mean.values,
        'population_ensemble_threshold': (posterior.mu_mean + posterior.mu_diff_mean).values,
        'mean_single_threshold': mean_single.values.mean(-1),
        'mean_ensemble_threshold': mean_multi.values.mean(-1),
        'mean_full_guess_probability': participant_array(posterior, 'lapse_rate_raw').values.mean(-1),
    }
    summary = []
    for name, values in draws.items():
        lo, hi = az.hdi(values.reshape(-1), hdi_prob=.95)
        summary.append(dict(quantity=name, mean=float(values.mean()), hdi_low=float(lo),
                            hdi_high=float(hi)))
    table = pd.DataFrame(summary)
    table.to_csv(out / 'summary.csv', index=False)
    return table
