"""Experiment 2: response-conditioned localization with a shared evidence SD.

The generated mass response, including guesses, selects localization direction.
Delta shifts conditional mass-response odds before state averaging and lapses.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import time
import statistics
import numpy as np
from scipy.special import expit, gammaln, ndtr
from scipy.stats import poisson

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / "data/experiment2"
RESULTS = ROOT / "results/experiment2"
LOOKUP = HERE / "lookup/mdN8"
# S1 order: both correct, CL only, MD only, neither. Guessing: MD=1/2, CL=5/25.
LAPSE = np.array([.1, .1, .4, .4])
SEEDS = dict(fit=42, figure=42, posterior_predictive=476, validation_base=923,
             direction_forward=423, direction_reverse=424, posterior_selection=879,
             posterior_simulation_base=1879)


def environment():
    names = ['numpy','scipy','pymc','pytensor','nutpie','numba','llvmlite','arviz','xarray','matplotlib']
    return dict(python=platform.python_version(), platform=platform.platform(),
                machine=platform.machine(), packages={n:importlib.metadata.version(n) for n in names},
                thread_limits={k:os.environ.get(k) for k in ['OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','PYTENSOR_FLAGS']})



def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def s2_truth(t):
    """Return lighter/same/heavier (0/1/2) from video order and target change."""
    flag = str(t['highlighted_cell_changed']).lower()
    if flag not in {'0','1','true','false'}:
        raise ValueError(f'Unknown changed flag: {flag}')
    if flag in {'0','false'}:
        return 1
    def sign(p):
        return -1 if '/lighter/' in p else 1 if '/heavier/' in p else 0
    difference = sign(t['video2'])-sign(t['video1'])
    if not difference:
        raise ValueError('Changed S2 trial has no identifiable direction')
    return 2 if difference > 0 else 0


def selected_data():
    """Select participants, apply the exclusion table, and count S1/S2 outcomes."""
    raw = json.loads((DATA/'data.json').read_text())
    # Require both answers correct on at least four of five catch trials.
    qualifying = []
    for s in raw:
        catches = [t for t in s['experiment1']['trials'].values() if t['is_catch']]
        if len(catches) != 5:
            raise ValueError('Expected exactly five S1 catch trials')
        for t in s['experiment1']['trials'].values():
            if t['perception_correct'] not in ('0','1') or t['grid_choice_correct'] not in ('0','1'):
                raise ValueError('Unknown S1 response correctness')
        if sum(t['perception_correct']=='1' and t['grid_choice_correct']=='1' for t in catches) >= 4:
            qualifying.append(s)
    selected = qualifying[:80]
    if len(selected) != 80:
        raise ValueError('Expected 80 eligible participants')
    # Apply exclusions by participant ID and within-section trial order.
    with (DATA/'excluded_trials.csv').open(newline='') as f:
        exclusions = list(csv.DictReader(f))
    removed = {(r['participant_id'], int(r['order'])) for r in exclusions}
    if len(removed) != 15 or any(r['section'] != 'S1' for r in exclusions):
        raise ValueError('Expected 15 distinct S1 exclusions')
    with (DATA/'participants.csv').open(newline='') as f:
        expected_ids = [r['participant_id'] for r in csv.DictReader(f) if r['included'] == '1']
    if [s['PROLIFIC_PID'] for s in selected] != expected_ids:
        raise ValueError('Participant selection/order changed')
    found = set()
    # S1 has four joint outcomes; S2 rows are truth and columns are responses.
    s1, s2 = [], []
    for s in selected:
        counts1, counts2 = [0]*4, [[0]*3 for _ in range(3)]
        for t in s['experiment1']['trials'].values():
            if t['is_catch']:
                continue
            key = (s['PROLIFIC_PID'], int(t['order']))
            if key in removed:
                found.add(key)
                continue
            cl, md = t['grid_choice_correct']=='1', t['perception_correct']=='1'
            counts1[0 if cl and md else 1 if cl else 2 if md else 3] += 1
        for t in s['experiment2']['trials'].values():
            if t.get('is_catch'):
                continue
            response = t['prediction'].strip().lower()
            if response not in ['lighter','same','heavier']:
                raise ValueError(f'Unknown S2 response: {response}')
            counts2[s2_truth(t)][['lighter','same','heavier'].index(response)] += 1
        s1.append(counts1)
        s2.append(counts2)
    if found != removed:
        raise ValueError("An excluded trial is missing or is a catch trial")
    return raw, qualifying, selected, s1, s2


def raw_summary():
    raw, qualifying, selected, s1, s2 = selected_data()
    individual = []
    for subject, a, b in zip(selected, s1, s2):
        den_same, den_change = sum(b[1]), sum(b[0])+sum(b[2])
        if not den_same or not den_change:
            raise ValueError('S2 conditional accuracy undefined for a participant')
        individual.append({'subject':subject['PROLIFIC_PID'],
                           'MD':(a[0]+a[2])/sum(a), 'CL':(a[0]+a[1])/sum(a),
                           'changed':(b[0][0]+b[2][2])/den_change, 'same':b[1][1]/den_same,
                           's1_n':sum(a), 'changed_n':den_change,'same_n':den_same})
    total1 = [sum(a[j] for a in s1) for j in range(4)]
    total2 = [[sum(b[i][j] for b in s2) for j in range(3)] for i in range(3)]
    counts = {'MD':(total1[0]+total1[2],sum(total1)), 'CL':(total1[0]+total1[1],sum(total1)),
              'changed':(total2[0][0]+total2[2][2],sum(total2[0])+sum(total2[2])),
              'same':(total2[1][1],sum(total2[1]))}
    return {'stored_participants':len(raw), 'eligible':len(qualifying), 'selected':len(selected),
            'selected_ids':[s['PROLIFIC_PID'] for s in selected],
            'eligible_not_selected':[s['PROLIFIC_PID'] for s in qualifying[80:]],
            'MD_only_eligible':sum(sum(t['perception_correct']=='1' for t in s['experiment1']['trials'].values()
                                     if t['is_catch'])>=4 for s in raw),
            's1_counts':total1,'s2_counts':total2,
            'accuracy':{k:{'participant_mean':statistics.mean(r[k] for r in individual),
                           'participant_sd':statistics.stdev(r[k] for r in individual),
                           'correct':v[0], 'trials':v[1], 'pooled':v[0]/v[1]} for k,v in counts.items()}}, individual


def cells_for(cap=8):
    """Enumerate (attended, changed attended, changed detected, unchanged detected)."""
    # Crossings are above +1 in the increasing-change reference direction.
    return np.array([(k, r, i, j) for k in range(cap + 1)
                     for r in range(max(0, k - 20), min(k, 5) + 1)
                     for i in range(r + 1) for j in range(k - r + 1)], dtype=np.int16)


def cell_constants(cells):
    k, r, i, j = cells.T
    # Hypergeometric probability of attending r changed items among k of 25.
    pr = np.array([math.comb(5, int(rr)) * math.comb(20, int(kk-rr)) /
                   math.comb(25, int(kk)) for kk, rr in zip(k, r)])
    # Choose among detected items; if none, guess among unattended locations.
    cl = np.divide(i, i+j, out=np.zeros(len(k), dtype=float), where=i+j > 0)
    cl = np.where(i+j > 0, cl, (5-r)/(25-k))
    lc = gammaln(r+1)-gammaln(i+1)-gammaln(r-i+1)
    lc += gammaln(k-r+1)-gammaln(j+1)-gammaln(k-r-j+1)
    return pr, cl, lc


class Lookup:
    """Integrate over attention states while preserving dependence between tasks."""
    def __init__(self, prefix):
        self.prefix = str(prefix)
        self.cells = np.load(f"{prefix}_cells.npy")
        self.a = np.load(f"{prefix}_alpha_grid.npy")
        self.b = np.load(f"{prefix}_logbeta_grid.npy")
        # F stores conditional CDFs of summed evidence at +1 and -1.
        self.f = np.load(f"{prefix}_F_table.npy")
        self.cap = int(self.cells[:, 0].max())
        if not np.array_equal(self.cells, cells_for(self.cap)):
            raise ValueError("Unexpected latent-state ordering")
        if self.f.shape != (len(self.a), len(self.b), len(self.cells), 2):
            raise ValueError("Lookup dimensions disagree")
        self.pr, self.cl, self.lc = cell_constants(self.cells)

        # H stores joint wrong-MD / correct-CL probability in each state.
        self.h = np.load(f'{prefix}_H_table.npy')
        if self.h.shape != self.f.shape[:-1]:
            raise ValueError('Response-gated H dimensions disagree')
        if (not np.isfinite(self.h).all() or np.min(self.h) < -1e-10 or
                np.max(self.h-.5*(self.f[..., 0]+self.f[..., 1])) > 1e-8):
            raise ValueError('H must lie within the conditional wrong-MD mass')
        self.table = np.concatenate([self.f, self.h[..., None]], axis=-1)

    def weights(self, lam, mu, sigma):
        k, r, i, j = self.cells.T
        pk = poisson.pmf(np.arange(self.cap+1)[None, :], lam[:, None])
        # Fold the entire Poisson upper tail into the attention cap.
        pk[:, -1] = poisson.sf(self.cap-1, lam)
        hit = ndtr((mu-1)/sigma)
        fa = ndtr(-1/sigma)
        hit, fa = np.clip(hit[:, None], 1e-12, 1-1e-12), np.clip(fa[:, None], 1e-12, 1-1e-12)
        binom = np.exp(self.lc + i*np.log(hit)+(r-i)*np.log1p(-hit) +
                       j*np.log(fa)+(k-r-j)*np.log1p(-fa))
        return pk[:, k]*self.pr*binom

    def _interpolate(self, mu, sigma):
        # Lookup coordinates standardize the evidence threshold by its SD.
        aa, bb = (1-mu)/sigma, -np.log(sigma)
        ia = np.clip(np.searchsorted(self.a, aa, side='right')-1, 0, len(self.a)-2)
        ib = np.clip(np.searchsorted(self.b, bb, side='right')-1, 0, len(self.b)-2)
        x = np.clip((aa-self.a[ia])/(self.a[ia+1]-self.a[ia]), 0, 1)[:, None, None]
        y = np.clip((bb-self.b[ib])/(self.b[ib+1]-self.b[ib]), 0, 1)[:, None, None]
        table = self.table
        v = ((1-x)*(1-y)*table[ia, ib]+x*(1-y)*table[ia+1, ib]+
             (1-x)*y*table[ia, ib+1]+x*y*table[ia+1, ib+1])
        # Stabilize probabilities in extreme tails before taking logits.
        f = np.clip(v[..., :2], 1e-7, 1-1e-7)
        # Inside the summed-evidence thresholds, MD guesses with probability 1/2.
        base = np.clip(1-.5*(f[..., 0]+f[..., 1]), 1e-12, 1-1e-12)
        # Divide joint mass by wrong-MD probability to condition localization.
        cl_wrong = np.clip(v[..., 2]/(1-base), 0, 1)
        return base, cl_wrong

    def collapse(self, weights, base, cl_wrong, delta):
        # Apply the boost within each state, then average the four joint outcomes.
        md = expit(np.log(base)-np.log1p(-base)+delta[:, None])
        out = np.stack([(weights*self.cl*md).sum(1),
                        (weights*cl_wrong*(1-md)).sum(1),
                        (weights*(1-self.cl)*md).sum(1),
                        (weights*(1-cl_wrong)*(1-md)).sum(1)], axis=1)
        return out/out.sum(1, keepdims=True)

    def predict(self, lam, mu, sigma, delta, return_zero=False):
        lam, mu, sigma, delta = (np.atleast_1d(x).astype(float) for x in (lam, mu, sigma, delta))
        base, cl_wrong = self._interpolate(mu, sigma)
        weights = self.weights(lam, mu, sigma)
        result = self.collapse(weights, base, cl_wrong, delta)
        if return_zero:
            return result, self.collapse(weights, base, cl_wrong, np.zeros_like(delta))
        return result

    def tensor_predict(self, lam, mu, sigma, delta):
        """Differentiable version of predict for posterior sampling."""
        import pytensor.tensor as pt
        from scipy.special import gammaln
        k, r, i, j = self.cells.T.astype('int64')
        ks = np.arange(self.cap+1)
        raw = pt.exp(-lam[:, None]+ks*pt.log(pt.maximum(lam[:, None], 1e-300))-gammaln(ks+1))
        pk = pt.concatenate([raw[:, :-1], pt.maximum(0, 1-raw[:, :-1].sum(1))[:, None]], axis=1)
        cdf = lambda z: .5*pt.erfc(-z/np.sqrt(2))
        hit = pt.clip(cdf((mu-1)/sigma)[:, None], 1e-12, 1-1e-12)
        fa = pt.clip(cdf(-1/sigma)[:, None], 1e-12, 1-1e-12)
        weights = pk[:, k]*self.pr*pt.exp(self.lc+i*pt.log(hit)+(r-i)*pt.log1p(-hit)+
                                         j*pt.log(fa)+(k-r-j)*pt.log1p(-fa))
        aa, bb = (1-mu)/sigma, -pt.log(sigma)
        ga, gb = pt.as_tensor_variable(self.a), pt.as_tensor_variable(self.b)
        ia = pt.clip(pt.searchsorted(ga, aa, side='right')-1, 0, len(self.a)-2)
        ib = pt.clip(pt.searchsorted(gb, bb, side='right')-1, 0, len(self.b)-2)
        x = pt.clip((aa-ga[ia])/(ga[ia+1]-ga[ia]), 0, 1)[:, None, None]
        y = pt.clip((bb-gb[ib])/(gb[ib+1]-gb[ib]), 0, 1)[:, None, None]
        table = pt.as_tensor_variable(self.table)
        v = ((1-x)*(1-y)*table[ia, ib]+x*(1-y)*table[ia+1, ib]+
             (1-x)*y*table[ia, ib+1]+x*y*table[ia+1, ib+1])
        f = pt.clip(v[..., :2], 1e-7, 1-1e-7)
        base = pt.clip(1-.5*(f[..., 0]+f[..., 1]), 1e-12, 1-1e-12)
        cl_wrong = pt.clip(v[..., 2]/(1-base), 0, 1)
        md = pt.sigmoid(pt.log(base)-pt.log1p(-base)+delta[:, None])
        out = pt.stack([(weights*self.cl*md).sum(1),
                        (weights*cl_wrong*(1-md)).sum(1),
                        (weights*(1-self.cl)*md).sum(1),
                        (weights*(1-cl_wrong)*(1-md)).sum(1)], axis=1)
        return out/out.sum(1, keepdims=True)


def s2_probabilities(mu, sigma):
    """S2 response probabilities from evidence below -1, inside [-1, 1], or above +1."""
    means = np.stack([-mu, np.zeros_like(mu), mu], axis=-1)
    low, high = ndtr((-1-means)/sigma[..., None]), ndtr((1-means)/sigma[..., None])
    return np.stack([low, high-low, 1-high], axis=-1)


def analytic_md(lam, mu, sigma, cap=8):
    """Exact pre-lapse, zero-boost marginal; independent of the CL rule."""
    out = 0.
    for k in range(cap+1):
        pk = poisson.sf(cap-1, lam) if k == cap else poisson.pmf(k, lam)
        for r in range(max(0, k-20), min(k, 5)+1):
            pr = math.comb(5, r)*math.comb(20, k-r)/math.comb(25, k)
            acc = .5 if k == 0 else .5+.5*(ndtr((r*mu-1)/(sigma*np.sqrt(k)))-ndtr((-1-r*mu)/(sigma*np.sqrt(k))))
            out += pk*pr*acc
    return out


def build_model(lookup, ids, s1, s2):
    import pymc as pm
    import pytensor.tensor as pt
    with pm.Model(coords={'subject': ids}) as model:
        def hierarchy(prefix, center, width, scale=1.):
            m = pm.Normal(prefix+'_mu', center, width)
            sd = pm.HalfNormal(prefix+'_sd', scale)
            z = pm.Normal('z_'+prefix[3:], 0, 1, dims='subject')
            return pm.Deterministic(prefix, m+sd*z, dims='subject')
        # Participant attention rate, changed-evidence mean, and shared evidence SD.
        lam = pm.Deterministic('λ', pt.exp(hierarchy('logλ', np.log(4), 2)), dims='subject')
        mu = pm.Deterministic('μ_gain', pt.softplus(hierarchy('logμ', .5, 5)), dims='subject')
        sigma = pm.Deterministic('σ', pt.exp(hierarchy('logσ', 0, 2)), dims='subject')
        # The ensemble boost is a participant-specific log-odds shift.
        dm = pm.Normal('delta_mu', 0, 2)
        ds = pm.HalfNormal('delta_sd', 1)
        z = pm.Normal('z_delta', 0, 1, dims='subject')
        delta = pm.Deterministic('delta', dm+ds*z, dims='subject')
        # One guessing probability per participant, shared across both sections.
        am = pm.Beta('alpha_mu', 2, 8)
        ak = pm.Gamma('alpha_kappa', 8, 1)
        alpha = pm.Beta('alpha', am*ak, (1-am)*ak, dims='subject')
        # S1 integrates over generated MD responses and conditional localization.
        p1 = lookup.tensor_predict(lam, mu, sigma, delta)
        p1 = (1-alpha[:, None])*p1+alpha[:, None]*LAPSE
        # S2 uses the same evidence parameters, with uniform three-way lapse guesses.
        means = pt.stack([-mu, pt.zeros_like(mu), mu], axis=1)
        cdf = lambda z: .5*pt.erfc(-z/np.sqrt(2))
        lo, hi = cdf((-1-means)/sigma[:, None]), cdf((1-means)/sigma[:, None])
        p2 = pt.stack([lo, hi-lo, 1-hi], axis=2)
        p2 = (1-alpha[:, None, None])*p2+alpha[:, None, None]/3
        # Fit both sections jointly to each participant's response counts.
        pm.Multinomial('s1_like', n=s1.sum(1), p=p1, observed=s1)
        pm.Multinomial('s2_like', n=s2.sum(2), p=p2, observed=s2)
    return model


def diagnostics(trace):
    import arviz as az
    names=['logλ_mu','logλ_sd','logμ_mu','logμ_sd','logσ_mu','logσ_sd',
           'alpha_mu','alpha_kappa','z_λ','z_μ','z_σ','alpha','λ','μ_gain','σ']
    names+=['delta_mu','delta_sd','z_delta','delta']
    summary=az.summary(trace,var_names=names,kind='diagnostics',round_to='none')
    result={'divergences':int(trace.sample_stats.diverging.sum()),
            'max_rhat':float(summary.r_hat.max()),
            'min_ess_bulk':float(summary.ess_bulk.min()),
            'min_ess_tail':float(summary.ess_tail.min())}
    result['passed']=(result['divergences']==0 and result['max_rhat']<=1.01 and
                      min(result['min_ess_bulk'],result['min_ess_tail'])>=400)
    return result,summary


def fit(out, lookup_prefix=LOOKUP, seed=SEEDS['fit'], draws=2000, tune=1000, cores=4, target_accept=.8):
    """Fit the paper model into a new directory."""
    import nutpie
    from numerics import validate
    if seed < 0 or draws < 1 or tune < 1 or cores < 1 or not 0 < target_accept < 1:
        raise ValueError('Invalid seed or sampling settings')
    lookup_prefix = Path(lookup_prefix).resolve()
    checked = validate(lookup_prefix)
    if not checked['passed']:
        raise RuntimeError('Lookup validation failed')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    _, _, selected, s1, s2 = selected_data()
    ids = [s['PROLIFIC_PID'] for s in selected]
    inputs = [HERE/n for n in ['model.py','numerics.py','lookup.py']]
    inputs += sorted(DATA.glob('*')) + sorted(lookup_prefix.parent.glob('mdN8_*.npy'))
    settings = dict(seed=seed, draws=draws, tune=tune, chains=4, cores=min(cores,4),
                    target_accept=target_accept, sampler='nutpie')
    manifest = dict(model='response-conditioned localization, shared evidence SD',
                    environment=environment(), selected_ids=ids, fit_settings=settings,
                    seeds={**SEEDS,'fit':seed}, status='running', lookup_validation=checked,
                    s1_counts=np.sum(s1, axis=0).tolist(), s2_counts=np.sum(s2, axis=0).tolist(),
                    inputs={str(p.relative_to(ROOT)):sha256(p) for p in inputs})
    dest = out/'provenance.json'
    dest.write_text(json.dumps(manifest,indent=2)+'\n')
    started = time.monotonic()
    try:
        fitted = build_model(Lookup(lookup_prefix), ids, np.array(s1), np.array(s2))
        compiled = nutpie.compile_pymc_model(fitted)
        trace = nutpie.sample(compiled, draws=draws, tune=tune, chains=4, cores=min(cores,4),
                              seed=seed, store_divergences=True, target_accept=target_accept)
        trace.posterior.attrs.update(model_variant='response-gated-free',selected_ids=json.dumps(ids),fit_seed=seed)
        trace.to_netcdf(out/'trace.nc')
        result, _ = diagnostics(trace)
        manifest.update(status='sampling_passed' if result['passed'] else 'failed',
                        trace_sha256=sha256(out/'trace.nc'), diagnostics=result)
    except BaseException as exc:
        manifest.update(status='failed', error=repr(exc))
        raise
    finally:
        manifest['seconds'] = time.monotonic()-started
        dest.write_text(json.dumps(manifest,indent=2)+'\n')
    if not result['passed']:
        raise RuntimeError('Sampling diagnostics failed; do not interpret the fit')
    return out/'trace.nc'
