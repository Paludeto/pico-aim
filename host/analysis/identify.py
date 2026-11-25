"""Identificacao da planta (spec 6.6 e 9) a partir do CSV de telemetria.

  python -m analysis.identify log_XXXX.csv

Modelo: integrador com ganho g [px/contagem] e atraso L [periodos de 1 ms]:
    e_m(k_r) = a - g * U(k_r - L - 1)
U e a soma acumulada dos comandos e k_r o passo em que a medicao chegou ao MCU
(tick - meas_age). Varre L e escolhe o de menor residuo. O L obtido e o valor
para --latency e g para --plant-gain. Latencia ponta a ponta = L * 1 ms.
"""
import argparse
import csv

import numpy as np

CTRL_HZ = 1000


def load(path):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    return {k: np.array([float(r[k]) for r in rows]) for k in rows[0]}


def fit_axis(tick, age, em, u, l_max=127.0, l_step=0.25):
    tick = np.unwrap(tick, period=65536.0)
    U = np.cumsum(u)                                # U(tick): comandos ate o passo 'tick'
    new = np.nonzero((age[1:] < age[:-1]) | (age[1:] == 0))[0] + 1   # chegou medicao nova
    if len(new) < 20 or np.ptp(U) == 0:
        return None
    kr, e = tick[new] - age[new], em[new]
    best = None
    for L in np.arange(0.0, l_max + l_step, l_step):
        x = np.interp(kr - L - 1.0, tick, U)
        A = np.stack([np.ones_like(x), -x], 1)
        coef, *_ = np.linalg.lstsq(A, e, rcond=None)
        resid = float(np.sqrt(np.mean((A @ coef - e) ** 2)))
        if best is None or resid < best["resid"]:
            best = {"L": float(L), "gain": float(coef[1]), "resid": resid, "n": len(new)}
    return best


def identify(path):
    d = load(path)
    sel = d["state"] == 2                           # so o trecho em IDENTIFICACAO
    if sel.sum() < 50:
        raise SystemExit("o log nao tem um trecho em modo IDENTIFICACAO")
    i0, i1 = np.nonzero(sel)[0][[0, -1]]
    s = slice(max(0, i0 - 5), min(len(sel), i1 + 40))
    return {ax: fit_axis(d["tick"][s], d["meas_age"][s], d[f"em_{ax}"][s], d[f"u_{ax}"][s]) for ax in "xy"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    a = ap.parse_args(argv)
    res = identify(a.csv)
    for ax, r in res.items():
        if r is None:
            print(f"eixo {ax}: dados insuficientes (o tracker estava rodando? o alvo estava visivel?)")
            continue
        print(f"eixo {ax}: ganho = {r['gain']:.3f} px/contagem   L = {r['L']:.2f} passos = {r['L'] * 1000.0 / CTRL_HZ:.1f} ms"
              f"   residuo = {r['resid']:.2f} px   ({r['n']} medicoes)")
    ok = [r for r in res.values() if r]
    if ok:
        L = round(float(np.mean([r["L"] for r in ok])))
        g = float(np.mean([r["gain"] for r in ok]))
        print(f"\nsugestao: python -m tracker --port ... --latency {L} --plant-gain {g:.2f}")
        if abs(g - 1.0) > 0.1:
            print("ganho longe de 1: confira 'Aumentar precisao do ponteiro' (desligado) e a sensibilidade 6/11.")
    return res


if __name__ == "__main__":
    main()
