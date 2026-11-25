"""Ensaio automatico da malha fechada na placa: identificacao, degrau e senoide.

  python tests/hw_loop.py COM5

Abre o app de teste, faz o papel do tracker e comanda os modos pela CDC. A
saida so existe depois de uma pressao curta no BOOTSEL: o script espera por
ela. ATENCAO: durante o ensaio o cursor do mouse e movido pela placa.
No fim (ou em qualquer erro) o modo volta a DESLIGADO.
"""
import argparse
import csv
import ctypes
import os
import subprocess
import sys
import time

import serial

HOST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, HOST)
from common import protocol as P                    # noqa: E402
from tracker import winutil                         # noqa: E402
from tracker.capture import Grabber                 # noqa: E402
from tracker.detect import detect_target            # noqa: E402
from analysis import identify, metrics              # noqa: E402


class Link:
    def __init__(self, port):
        self.ser = serial.Serial(port, 115200, timeout=0, write_timeout=1)
        self.parser = P.FrameParser()
        self.seq = 0
        self.last = None
        self.nacks = []

    def poll(self, sink=None, t=0.0):
        d = self.ser.read(8192)
        if not d:
            return
        for ftype, payload in self.parser.feed(d):
            if ftype == P.T_TELEM:
                self.last = P.unpack_telem(payload)
                if sink is not None:
                    sink.append(dict(self.last, t=t))
            elif ftype == P.T_ACK and payload[1] != P.ERR_OK:
                self.nacks.append((payload[0], P.ERR_NAMES[payload[1]]))

    def wait(self, dur):
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < dur:
            self.poll()
            time.sleep(0.001)

    def set(self, pid, value):
        self.ser.write(P.pack_set_param(pid, P.to_raw(pid, value)))
        self.wait(0.03)

    def mode(self, m):
        self.ser.write(P.pack_set_mode(m))
        self.wait(0.03)

    def meas(self, ex, ey, valid):
        self.seq = (self.seq + 1) & 0xFF
        self.ser.write(P.pack_meas(self.seq, ex, ey, valid))


def set_topmost(title):
    """Mantem a janela do app de teste na frente (senao outra janela cobre o alvo)."""
    u = ctypes.windll.user32
    hwnd = u.FindWindowW(None, title)
    if hwnd:
        u.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)   # TOPMOST, sem mover/redimensionar


def run_phase(link, name, app_args, dur, mode, outdir, size):
    """Roda o testapp por 'dur' s com o MCU em 'mode'. Retorna (csv do testapp, csv de telemetria, resumo)."""
    app_csv = os.path.join(outdir, name + "_app.csv")
    tel_csv = os.path.join(outdir, name + "_telem.csv")
    proc = subprocess.Popen([sys.executable, "-m", "testapp", "--size", size, "--duration", str(dur + 3.0),
                             "--log", app_csv] + app_args, cwd=HOST,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rows, n_meas, n_valid = [], 0, 0
    try:
        region, t0 = None, time.perf_counter()
        while region is None and time.perf_counter() - t0 < 10:
            region = winutil.window_client_rect(P.WINDOW_TITLE)
            time.sleep(0.1)
        if region is None:
            raise RuntimeError("a janela do app de teste nao abriu")
        t_app0 = time.perf_counter() - 0.1         # t = 0 do log do testapp (aprox.)
        set_topmost(P.WINDOW_TITLE)
        time.sleep(0.7)
        region = winutil.window_client_rect(P.WINDOW_TITLE)
        grabber = Grabber(region, "mss")
        t0 = time.perf_counter()
        nxt, started, t_mode = t0, False, t0 + 0.5
        while True:
            now = time.perf_counter()
            t = now - t0
            if t >= dur:
                break
            if not started and t >= 0.5:            # link estabelecido antes de ligar o modo
                link.ser.write(P.pack_set_mode(mode))
                started, t_mode = True, now
            if now >= nxt:
                nxt = max(nxt + 1 / 60, now)
                img = grabber.grab()
                cx, cy = winutil.cursor_pos()
                pos = detect_target(img) if img is not None else None
                n_meas += 1
                if pos is None:
                    link.meas(0, 0, False)
                else:
                    n_valid += 1
                    link.meas(round(region[0] + pos[0] - cx), round(region[1] + pos[1] - cy), True)
            link.poll(rows, t)
            time.sleep(0.0003)
    finally:
        t_end = time.perf_counter()
        link.mode(P.MODE_OFF)
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
    with open(tel_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(("t",) + P.TELEM_FIELDS)
        for r in rows:
            w.writerow([f"{r['t']:.4f}"] + [r[c] for c in P.TELEM_FIELDS])
    # O testapp registra antes e depois do controle ativo: as metricas usam so o
    # trecho ativo (com 1 s de folga no inicio para o transitorio de captura).
    lo, hi = t_mode - t_app0 + 1.0, t_end - t_app0 - 0.3
    with open(app_csv, newline="") as f:
        app_rows = list(csv.reader(f))
    trim_csv = os.path.join(outdir, name + "_trim.csv")
    with open(trim_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(app_rows[0])
        w.writerows(r for r in app_rows[1:] if lo <= float(r[0]) <= hi)
    app_csv = trim_csv
    moved = sum(abs(r["u_x"]) + abs(r["u_y"]) for r in rows)
    info = {"meas": n_meas, "valid": n_valid, "fps": n_meas / dur, "telem": len(rows), "counts": moved,
            "drop": rows[-1]["hid_drop"] if rows else None,
            "load0": max(r["load0"] for r in rows) if rows else None,
            "load1": max(r["load1"] for r in rows) if rows else None}
    print(f"[{name}] medicoes {n_meas} ({n_valid} validas, {info['fps']:.0f} Hz), telemetria {len(rows)} quadros, "
          f"|u| total {moved} contagens, hid_drop {info['drop']}, carga max {info['load0']:.1f}/{info['load1']:.1f}%",
          flush=True)
    return app_csv, tel_csv, info


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port")
    ap.add_argument("--out", default="hw_loop_logs")
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--wait", type=float, default=540.0, help="espera maxima pelo BOOTSEL [s]")
    ap.add_argument("--no-wait", action="store_true", help="roda desabilitado (so confere o encanamento)")
    ap.add_argument("--kp", type=float, default=0.06)
    ap.add_argument("--ki", type=float, default=0.0)
    ap.add_argument("--no-estimator", action="store_true")
    ap.add_argument("--latency", type=int, default=None, help="pula a identificacao e usa este L")
    ap.add_argument("--plant-gain", type=float, default=None)
    ap.add_argument("--phases", default="ident,step,sine,ramp,smooth")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    winutil.set_dpi_aware()
    phases = a.phases.split(",")
    link = Link(a.port)
    try:
        link.mode(P.MODE_OFF)
        link.wait(0.3)
        if link.last is None:
            raise SystemExit("sem telemetria: a porta esta certa?")
        if not a.no_wait and not link.last["enabled"]:
            print(f">>> De uma pressao CURTA no BOOTSEL para habilitar (espero ate {a.wait:.0f} s)...", flush=True)
            t0 = time.perf_counter()
            while not link.last["enabled"]:
                if time.perf_counter() - t0 > a.wait:
                    raise SystemExit("tempo esgotado esperando o BOOTSEL")
                link.wait(0.1)
            print(f"habilitado apos {time.perf_counter() - t0:.0f} s", flush=True)
            link.wait(1.0)

        for pid, v in ((P.P_KP, a.kp), (P.P_KI, a.ki), (P.P_KD, 0.0), (P.P_DEADBAND, 1), (P.P_ID_AMP, 1),
                       (P.P_EST_EN, int(not a.no_estimator)), (P.P_PLANT_GAIN, a.plant_gain or 1.0), (P.P_LATENCY, a.latency or 30)):
            link.set(pid, v)

        if "ident" in phases and a.latency is None:
            # alvo parado: um "degrau" com periodo enorme
            _, tel, _ = run_phase(link, "ident", ["--mode", "step", "--period", "1000"], 5.5, P.MODE_IDENT, a.out, a.size)
            try:
                res = identify.identify(tel)
            except SystemExit as e:
                res = {}
                print(f"[ident] {e}")
            ok = [r for r in res.values() if r]
            for ax, r in res.items():
                if r:
                    print(f"[ident] eixo {ax}: ganho {r['gain']:.3f} px/contagem, L = {r['L']:.2f} ms, "
                          f"residuo {r['resid']:.2f} px ({r['n']} medicoes)")
            if ok:
                L = round(sum(r["L"] for r in ok) / len(ok))
                g = sum(r["gain"] for r in ok) / len(ok)
                if 2 <= L <= 120 and 0.2 <= g <= 6:
                    link.set(P.P_LATENCY, L)
                    link.set(P.P_PLANT_GAIN, g)
                    print(f"[ident] aplicado: L = {L}, ganho da planta = {g:.3f}", flush=True)
                else:
                    print(f"[ident] resultado fora do razoavel (L = {L}, g = {g:.2f}); mantendo os valores atuais")

        tests = {
            "step": (["--mode", "step", "--step-size", "500", "--period", "1.5"], 12.0),
            "sine": (["--mode", "sine", "--freq", "0.5", "--amp", "300"], 10.0),
            "ramp": (["--mode", "ramp", "--speed", "300"], 10.0),
            "smooth": (["--mode", "smooth"], 10.0),
        }
        for name in phases:
            if name not in tests:
                continue
            args, dur = tests[name]
            app, _, _ = run_phase(link, name, args, dur, P.MODE_AUTO, a.out, a.size)
            r, _ = metrics.analyze(app)
            if "steps" in r and r["steps"]:
                print(f"[{name}] {len(r['steps'])} degraus de {r['amp']:.0f} px: overshoot {r['overshoot']:.1f}%, "
                      f"subida {r['rise_ms']:.0f} ms, acomodacao 2% {r['settle_ms']:.0f} ms (max {r['settle_max_ms']:.0f}), "
                      f"regime {r['ss_err']:.1f} px, nao acomodaram: {r['not_settled']}")
            if "rms" in r:
                print(f"[{name}] erro RMS {r['rms']:.1f} px, atraso {r['delay_ms']:.0f} ms")
            sys.stdout.flush()
        if link.nacks:
            print("NACKs:", link.nacks)
    finally:
        link.mode(P.MODE_OFF)
        link.wait(0.2)
        if link.last:
            print(f"fim: estado {P.STATE_NAMES[link.last['state']]}, habilitado {link.last['enabled']}, "
                  f"erros de protocolo {link.last['errs']}")
        link.ser.close()


if __name__ == "__main__":
    main()
