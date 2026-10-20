"""Integrate both signs once, then collapse to 420 conditional states.

Six evidence components (changed/unchanged x positive/inside/negative)
preserve the dependence of the selected direction, item crossings and sum.
No sampling or random seed is involved in this deterministic FFT quadrature.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.fft import next_fast_len, rfft, irfft
from scipy.special import gammaln, log_ndtr

import model
cells_for = model.cells_for

def interval_mass(lo, hi, mean):
    """Stable standard-normal interval masses, including extreme tails."""
    lo, hi = np.asarray(lo)-mean, np.asarray(hi)-mean
    # Reflect intervals in the right tail to avoid subtracting CDFs near one.
    reflect = lo > 0
    left, right = np.where(reflect, -hi, lo), np.where(reflect, -lo, hi)
    lr, ll = log_ndtr(right), log_ndtr(left)
    with np.errstate(invalid='ignore', divide='ignore', over='ignore'):
        logp = lr+np.log(-np.expm1(np.minimum(ll-lr, 0)))
    return np.where(hi > lo, logp, -np.inf)



def signed_cells(cap=8):
    return np.array([(c, k, r, i, j, u, v)
                     for c, (k, r, i, j) in enumerate(cells_for(cap))
                     for u in range(r-i+1) for v in range(k-r-j+1)], dtype=np.int16)


def signed_component(z, dz, mean, beta, sign):
    lo, hi = z-dz/2, z+dz/2
    if sign == 1:
        lo = np.maximum(lo, beta)
    elif sign == -1:
        hi = np.minimum(hi, -beta)
    elif sign == 0:
        lo, hi = np.maximum(lo, -beta), np.minimum(hi, beta)
    else:
        raise ValueError(sign)
    logp = interval_mass(lo, hi, mean)
    p = np.exp(logp-np.max(logp))
    return p/p.sum()


def build_point(alpha, logbeta, dz=.04, cap=8):
    cells = signed_cells(cap)
    c, k, r, i, j, u, v = cells.T
    beta, eta = np.exp(logbeta), np.exp(logbeta)-alpha
    radius = int(np.ceil((abs(eta)+beta+10)/dz))
    z = np.arange(-radius, radius+1)*dz
    length = next_fast_len(2*cap*radius+1)
    fourier = [rfft(signed_component(z, dz, m, beta, sign), n=length)
               for m in (eta, 0.) for sign in (1, 0, -1)]
    powers = [[f**n for n in range(cap+1)] for f in fourier]
    # Probability of negative crossing given no positive crossing, conditional
    # on C. Use log interval ratios, also for extremely unlikely tail states.
    log_neg = np.array([interval_mass(-np.inf, -beta, m) for m in (eta, 0.)])
    log_rest = np.array([interval_mass(-np.inf, beta, m) for m in (eta, 0.)])
    neg = np.clip(np.exp(log_neg-log_rest), 1e-300, 1-1e-15)
    nc, nu = r-i, k-r-j
    lw = (gammaln(nc+1)-gammaln(u+1)-gammaln(nc-u+1)+u*np.log(neg[0])+(nc-u)*np.log1p(-neg[0])+
          gammaln(nu+1)-gammaln(v+1)-gammaln(nu-v+1)+v*np.log(neg[1])+(nu-v)*np.log1p(-neg[1]))
    weights = np.exp(lw)
    cl_minus = np.divide(u, u+v, out=np.zeros(len(c)), where=u+v > 0)
    cl_minus = np.where(u+v > 0, cl_minus, (5-r)/(25-k))
    result = np.zeros((len(cells_for(cap)), 3))
    for start in range(0, len(cells), 24):
        sub = cells[start:start+24]
        products = np.stack([powers[0][ii]*powers[1][rr-ii-uu]*powers[2][uu]*
                             powers[3][jj]*powers[4][kk-rr-jj-vv]*powers[5][vv]
                             for cc, kk, rr, ii, jj, uu, vv in sub])
        pmfs = np.maximum(irfft(products, n=length, axis=1), 0)
        pmfs /= pmfs.sum(1, keepdims=True)
        cdfs = np.cumsum(pmfs, axis=1)
        for q, (cc, kk, rr, ii, jj, uu, vv) in enumerate(sub):
            tails = []
            for threshold in (beta, -beta):
                if kk == 0:
                    tails.append(float(threshold > 0))
                    continue
                at = threshold/dz+kk*radius+.5
                ix = int(np.floor(at))
                value = (0. if ix <= 0 else 1. if ix >= length else
                         cdfs[q, ix-1]+(at-ix)*pmfs[q, ix])
                tails.append(np.clip(value, 0, 1))
            wrong = .5*(tails[0]+tails[1])
            result[cc] += weights[start+q]*np.array([*tails, wrong*cl_minus[start+q]])
    return result


def worker(job):
    i, j, a, b, dz = job
    return i, j, build_point(a, b, dz)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--dz', type=float, default=.04)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    a = np.unique(np.r_[[-40., -30., -25., -20., -16., -13., -11., -9., -8., -7.],
                        np.linspace(-6, 2, 65), np.linspace(2, 6, 17)])
    b = np.linspace(-1.5, 2.5, 51)
    table = np.empty((len(a), len(b), len(cells_for()), 3))
    started = time.monotonic()
    jobs = [(i, j, float(x), float(y), args.dz) for i, x in enumerate(a) for j, y in enumerate(b)]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for count, (i, j, value) in enumerate(pool.map(worker, jobs, chunksize=1), 1):
            table[i, j] = value
            if count % 200 == 0:
                print(f'{count}/{len(jobs)} grid points; {time.monotonic()-started:.1f}s', flush=True)
    prefix = args.out/'mdN8'
    for name, value in [('cells', cells_for()), ('alpha_grid', a), ('logbeta_grid', b),
                        ('F_table', table[..., :2]), ('H_table', table[..., 2])]:
        np.save(f'{prefix}_{name}.npy', value)
    sources = [Path(__file__), Path(__file__).with_name('model.py')]
    manifest = {'mode': 'response-gated', 'cap': 8, 'threshold': 1, 'dz_sigma_units': args.dz,
                'signed_integration_states': len(signed_cells()), 'fitted_latent_states': len(cells_for()),
                'workers': args.workers, 'seconds': time.monotonic()-started,
                'sources': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                'files': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.out.glob('*.npy')}}
    (args.out/'lookup_manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(prefix, flush=True)


if __name__ == '__main__':
    main()
