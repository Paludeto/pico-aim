"""Metricas de rastreamento a partir do CSV do testapp (spec 8.3).

  python -m analysis.metrics a.csv [b.csv ...] [--plot]

Degrau: overshoot, tempo de subida (10-90%), acomodacao (2%) e erro em regime.
Rampa / senoide / suave: erro RMS, atraso (melhor casamento alvo x cursor) e defasagem.
Com varios arquivos, imprime uma tabela lado a lado (ex.: ganhos diferentes,
com e sem estimador).
"""
import argparse
import csv
import os

import numpy as np


def load(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit(f"{path}: vazio")
    cols = {k: np.array([float(r[k]) for r in rows]) for k in ("t", "target_x", "target_y", "cursor_x", "cursor_y")}
    cols["mode"] = np.array([r["mode"] for r in rows])
    return cols


def step_metrics(d, min_jump=20.0):
    """Uma entrada por salto do alvo."""
    t = d["t"]
    tgt = np.stack([d["target_x"], d["target_y"]], 1)
    cur = np.stack([d["cursor_x"], d["cursor_y"]], 1)
    jumps = np.nonzero(np.linalg.norm(np.diff(tgt, axis=0), axis=1) > min_jump)[0] + 1
    out = []
    for n, i in enumerate(jumps):
        j = jumps[n + 1] if n + 1 < len(jumps) else len(t)
        if j - i < 10:
            continue
        p0, p1 = cur[i - 1], tgt[i]
        amp = np.linalg.norm(p1 - p0)
        if amp < min_jump:
            continue
        unit = (p1 - p0) / amp
        tt = t[i:j] - t[i]
        s = (cur[i:j] - p0) @ unit                  # avanco ao longo do salto
        dist = np.linalg.norm(cur[i:j] - p1, axis=1)
        over = max(0.0, (s.max() - amp) / amp * 100.0)
        i10 = np.argmax(s >= 0.1 * amp) if (s >= 0.1 * amp).any() else None
        i90 = np.argmax(s >= 0.9 * amp) if (s >= 0.9 * amp).any() else None
        rise = (tt[i90] - tt[i10]) if i10 is not None and i90 is not None else float("nan")
        outside = np.nonzero(dist > max(0.02 * amp, 1.0))[0]
        if len(outside) == 0:
            settle = 0.0
        elif outside[-1] + 1 < len(tt):
            settle = tt[outside[-1] + 1]
        else:
            settle = float("nan")                   # nao acomodou antes do proximo salto
        tail = dist[int(len(dist) * 0.8):]
        out.append({"amp": amp, "overshoot": over, "rise_ms": rise * 1e3,
                    "settle_ms": settle * 1e3, "ss_err": float(tail.mean())})
    return out


def tracking_metrics(d):
    """Erro RMS e atraso entre alvo e cursor (trajetorias continuas)."""
    t = d["t"]
    ex, ey = d["target_x"] - d["cursor_x"], d["target_y"] - d["cursor_y"]
    skip = t >= t[0] + 1.0                           # descarta o transitorio inicial
    if skip.sum() < 20:
        skip[:] = True
    rms = float(np.sqrt(np.mean(ex[skip] ** 2 + ey[skip] ** 2)))
    # atraso: reamostra a 1 kHz e procura tau que minimiza |alvo(t - tau) - cursor(t)|
    dt = 1e-3
    tu = np.arange(t[skip][0], t[-1], dt)
    a = np.interp(tu, t, d["target_x"])
    b = np.interp(tu, t, d["cursor_x"])
    max_lag = min(500, len(tu) // 4)
    best, delay = np.inf, 0.0
    if a.std() > 1e-6:
        for lag in range(0, max_lag):                # menor erro quadratico medio
            c = float(np.mean((a[:len(a) - lag] - b[lag:]) ** 2))
            if c < best:
                best, delay = c, lag * dt
    a = a - a.mean()
    # frequencia dominante do alvo (para a defasagem)
    spec = np.abs(np.fft.rfft(a))
    freqs = np.fft.rfftfreq(len(a), dt)
    f0 = float(freqs[1:][np.argmax(spec[1:])]) if len(spec) > 2 else float("nan")
    return {"rms": rms, "delay_ms": delay * 1e3, "freq": f0, "phase_deg": 360.0 * f0 * delay}


def analyze(path):
    d = load(path)
    res = {"file": os.path.basename(path), "n": len(d["t"])}
    modes = set(d["mode"])
    res["mode"] = "+".join(sorted(modes))
    if "step" in modes:
        m = d["mode"] == "step"
        steps = step_metrics({k: v[m] for k, v in d.items()})
        res["steps"] = steps
        if steps:
            for k in ("amp", "overshoot", "rise_ms", "settle_ms", "ss_err"):
                vals = np.array([s[k] for s in steps])
                res[k] = float(np.nanmean(vals)) if not np.all(np.isnan(vals)) else float("nan")
            res["settle_max_ms"] = float(np.nanmax([s["settle_ms"] for s in steps])) \
                if not all(np.isnan(s["settle_ms"]) for s in steps) else float("nan")
            res["not_settled"] = int(sum(np.isnan(s["settle_ms"]) for s in steps))
    cont = np.isin(d["mode"], ("ramp", "sine", "smooth"))
    if cont.sum() > 50:
        res.update(tracking_metrics({k: v[cont] for k, v in d.items()}))
    return res, d


def report(results):
    for r in results:
        print(f"\n== {r['file']}  (modo: {r['mode']}, {r['n']} amostras)")
        if "steps" in r:
            print(f"  degraus: {len(r['steps'])}  amplitude media: {r.get('amp', float('nan')):.0f} px")
            print(f"  overshoot medio:      {r['overshoot']:.1f} %      (meta < 10 %)")
            print(f"  tempo de subida:      {r['rise_ms']:.0f} ms")
            print(f"  acomodacao 2% media:  {r['settle_ms']:.0f} ms  max: {r['settle_max_ms']:.0f} ms"
                  f"  (meta < 250 ms p/ 500 px)" + (f"  [{r['not_settled']} nao acomodaram]" if r["not_settled"] else ""))
            print(f"  erro em regime:       {r['ss_err']:.1f} px      (meta <= 2 px)")
        if "rms" in r:
            print(f"  erro RMS:             {r['rms']:.1f} px")
            print(f"  atraso alvo->cursor:  {r['delay_ms']:.0f} ms"
                  f"  (f = {r['freq']:.2f} Hz -> defasagem {r['phase_deg']:.1f} graus)")
    if len(results) > 1:
        print("\n" + f"{'arquivo':<32}{'oversh%':>9}{'acom ms':>9}{'regime px':>10}{'RMS px':>9}{'atraso ms':>10}")
        for r in results:
            g = lambda k: f"{r[k]:.1f}" if k in r else "-"     # noqa: E731
            print(f"{r['file'][:31]:<32}{g('overshoot'):>9}{g('settle_ms'):>9}{g('ss_err'):>10}{g('rms'):>9}{g('delay_ms'):>10}")


def plot(results, datas, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    for r, d in zip(results, datas):
        axes[0].plot(d["t"], d["cursor_x"], lw=1.2, label=f"cursor x ({r['file']})")
        err = np.hypot(d["target_x"] - d["cursor_x"], d["target_y"] - d["cursor_y"])
        axes[1].plot(d["t"], err, lw=1.0, label=r["file"])
    axes[0].plot(datas[0]["t"], datas[0]["target_x"], "k--", lw=1.0, label="alvo x")
    axes[0].set_ylabel("posicao x [px]")
    axes[1].set_ylabel("erro [px]")
    axes[1].set_xlabel("t [s]")
    for ax in axes:
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="upper right")
    fig.tight_layout()
    fig.savefig(out, dpi=120)
    print(f"\ngrafico: {out}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--plot", action="store_true", help="salva um PNG ao lado do primeiro CSV")
    a = ap.parse_args(argv)
    results, datas = zip(*(analyze(p) for p in a.csv))
    report(results)
    if a.plot:
        plot(results, datas, os.path.splitext(a.csv[0])[0] + ".png")
    return results


if __name__ == "__main__":
    main()
