"""Teste do firmware na placa, pela CDC: protocolo, temporizacao do passo,
failsafe e persistencia. Nao habilita a saida (so o BOOTSEL fisico faz isso),
entao o cursor nao se move. Grava a flash (termina com L = 30 salvo).

  python tests/hw_check.py COM5
"""
import os
import sys
import time

import numpy as np
import serial

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from common import protocol as P  # noqa: E402

ser = serial.Serial(sys.argv[1], 115200, timeout=0, write_timeout=1)
parser = P.FrameParser()
fails = 0


def check(ok, msg):
    global fails
    fails += not ok
    print(("ok    " if ok else "FALHA ") + msg)


def pump(dur, tx=None, period=None):
    """Le por 'dur' s; opcionalmente chama tx() a cada 'period' s. Retorna os quadros."""
    out, t0, nxt = [], time.perf_counter(), time.perf_counter()
    while time.perf_counter() - t0 < dur:
        if tx and time.perf_counter() >= nxt:
            nxt += period
            tx()
        d = ser.read(4096)
        if d:
            out += parser.feed(d)
        else:
            time.sleep(0.0005)
    return out


def cmd(data, dur=0.15):
    ser.write(data)
    return pump(dur)


def acks(frames):
    return [(p[0], p[1]) for t, p in frames if t == P.T_ACK]


def params(frames):
    return [P.unpack_params(p) for t, p in frames if t == P.T_PARAMS]


pump(0.3)
# 1. parametros
prm = params(cmd(P.pack_get_params()))
check(len(prm) == 1, f"GET_PARAMS responde: {prm[0] if prm else None}")

# 2. telemetria em repouso
rows = P.telem_rows(pump(2.0))
t_us = np.array([r["t_us"] for r in rows], dtype=np.int64)
tick = np.array([r["tick"] for r in rows], dtype=np.int64)
dt = np.diff(t_us) % (1 << 32)
dk = np.diff(tick) % 65536
ok = dk == 5                                    # quadros consecutivos (sem descarte)
check(180 <= len(rows) / 2.0 <= 220, f"taxa da telemetria: {len(rows) / 2.0:.0f} Hz")
check(ok.mean() > 0.98, f"quadros consecutivos: {100 * ok.mean():.1f}%")
per = dt[ok] / 5.0
print(f"      periodo do passo (media de 5): {per.mean():.2f} us, min {per.min():.1f}, max {per.max():.1f}, "
      f"desvio {per.std():.2f} us")
check(abs(per.mean() - 1000) < 1 and per.max() - per.min() < 20, "periodo de 1 ms sem deriva")
r = rows[-1]
check(r["state"] == 0 and r["enabled"] == 0 and r["link_ok"] == 0, f"boot: DESLIGADO, desabilitado, sem link")
print(f"      carga: core 0 = {np.mean([x['load0'] for x in rows]):.1f}%, core 1 = {np.mean([x['load1'] for x in rows]):.1f}%")
errs0 = r["errs"]

# 3. validacao de faixas
a = acks(cmd(P.pack_set_param(P.P_KP, P.to_raw(P.P_KP, 20.0))))
check(a == [(P.T_SET_PARAM, P.ERR_RANGE)], f"Kp = 20 -> NACK faixa {a}")
a = acks(cmd(P.pack_set_param(P.P_LATENCY, 45)))
check(a == [(P.T_SET_PARAM, P.ERR_OK)], f"L = 45 -> ACK {a}")
a = acks(cmd(P.pack_set_mode(9)))
check(a == [(P.T_SET_MODE, P.ERR_MODE)], f"modo 9 -> NACK {a}")
prm = params(cmd(P.pack_get_params()))
check(prm and prm[0]["latency"] == 45 and abs(prm[0]["kp"] - 0.06) < 1e-3, "leitura: L = 45, Kp intacto")

# 4. link: MEAS a 60 Hz em AUTOMATICO, mas desabilitado -> u = 0
a = acks(cmd(P.pack_set_mode(P.MODE_AUTO)))
check(a == [(P.T_SET_MODE, P.ERR_OK)], "SET_MODE AUTOMATICO -> ACK")
seq = [0]


def meas():
    seq[0] = (seq[0] + 1) & 0xFF
    ser.write(P.pack_meas(seq[0], 123, -45))


rows = P.telem_rows(pump(1.0, meas, 1 / 60))
r = rows[-1]
check(r["link_ok"] == 1 and r["state"] == 1 and (r["em_x"], r["em_y"]) == (123, -45), f"link ativo, e_m = ({r['em_x']},{r['em_y']})")
check(all(x["u_x"] == 0 and x["u_y"] == 0 for x in rows) and r["enabled"] == 0, "desabilitado: u = 0 (cursor parado)")
ages = [x["meas_age"] for x in rows[20:]]
print(f"      idade da medicao: max {max(ages)} ms")

# failsafe: para de enviar e mede quando o link cai
t_stop = time.perf_counter()
rows = P.telem_rows(pump(0.4))
down = [x for x in rows if not x["link_ok"]]
up = [x for x in rows if x["link_ok"]]
if down and up:
    gap = ((down[0]["t_us"] - up[-1]["t_us"]) % (1 << 32)) / 1000.0
    last_meas = up[-1]["meas_age"]
    print(f"      link caiu com meas_age = {down[0]['meas_age']} ms (ultimo quadro com link: {last_meas} ms, +{gap:.0f} ms)")
check(bool(down) and 100 <= down[0]["meas_age"] <= 105, "failsafe: link perdido em 100 ms")

# 5. erros de protocolo
f = P.pack_meas(50, 1, 1)
ser.write(f[:-1] + bytes([f[-1] ^ 0x55]))       # CRC errado
pump(0.05)
rows = P.telem_rows(pump(0.3, meas, 1 / 60))    # link de volta
ser.write(P.pack_meas(seq[0], 1, 1))            # SEQ repetido
rows = P.telem_rows(pump(0.2, meas, 1 / 60))
check(rows[-1]["errs"] - errs0 == 4, f"erros contados: {rows[-1]['errs'] - errs0} (2 NACK + CRC + SEQ)")

# 6. persistencia
a = acks(cmd(P.pack_save()))
check(a == [(P.T_SAVE, P.ERR_STATE)], f"SAVE em AUTOMATICO -> NACK estado {a}")
cmd(P.pack_set_mode(P.MODE_OFF))
fr = cmd(P.pack_set_param(P.P_LATENCY, 31), 0.2)       # valor diferente do salvo: forca a gravacao
ser.write(P.pack_save())
fr += pump(0.5)
check((P.T_SAVE, P.ERR_OK) in acks(fr), "SAVE em DESLIGADO -> ACK")
# o fluxo e continuo desde antes do SAVE: a pausa do core 1 aparece como um intervalo maior
rows = P.telem_rows(fr)
gaps = (np.diff([x["t_us"] for x in rows]) % (1 << 32)) / 1000.0 - 5.0
check(5 < gaps.max() < 450, f"core 1 pausado durante a gravacao da flash: {gaps.max():.1f} ms")
cmd(P.pack_set_param(P.P_LATENCY, 30))          # o que fica gravado sao os valores padrao
cmd(P.pack_save(), 0.5)
cmd(P.pack_set_param(P.P_LATENCY, 77))
a = acks(cmd(P.pack_load()))
prm = params(cmd(P.pack_get_params()))
check(a == [(P.T_LOAD, P.ERR_OK)] and prm and prm[0]["latency"] == 30, f"LOAD recupera L = {prm[0]['latency'] if prm else None}")

# 7. depois da gravacao o controle continua a 1 kHz
rows = P.telem_rows(pump(1.0))
dk = np.diff([x["tick"] for x in rows]) % 65536
dt = (np.diff([x["t_us"] for x in rows]) % (1 << 32))[dk == 5] / 5.0
check(len(rows) > 180 and abs(dt.mean() - 1000) < 1, f"apos a gravacao: {len(rows)} quadros/s, periodo {dt.mean():.2f} us")
check(rows[-1]["state"] == 0 and rows[-1]["enabled"] == 0, "termina em DESLIGADO e desabilitado")

ser.close()
print(f"\n{fails} falha(s)")
sys.exit(1 if fails else 0)
