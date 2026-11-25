"""Tracker (spec 8.1): captura a janela do app de teste, detecta o alvo, le o
cursor, envia o erro ao RP2040 (USB CDC) e grava a telemetria.

  python -m tracker --port COM5
  python -m tracker --port COM5 --kp 0.06 --ki 2 --latency 30 --mode auto
  python -m tracker --port COM5 --no-estimator                    # comparacao

Sem argumentos de parametro, valem os que estao no MCU (padrao ou flash).
A saida so existe depois de HABILITAR no botao BOOTSEL da placa.

Teclas (Windows, com o terminal em foco):
  0 / 1 / 2   modo DESLIGADO / AUTOMATICO / IDENTIFICACAO
  k i d       seleciona Kp / Ki / Kd          l  latencia L      z  zona morta
  g           ganho da planta                 f  filtro da derivada
  + / -       aumenta / diminui o parametro selecionado
  e           liga / desliga o estimador
  s           salva na flash (so em DESLIGADO)        o  carrega da flash
  q           sai
"""
import argparse
import csv
import sys
import time

import serial

from common import protocol as P
from . import winutil
from .capture import Grabber
from .detect import detect_target

MODES = {"off": P.MODE_OFF, "auto": P.MODE_AUTO, "ident": P.MODE_IDENT}

# tecla -> (id, nome, tipo de passo, passo, minimo, maximo), em unidade fisica.
# Passo "mul": multiplica/divide; "add": soma/subtrai.
ADJUST = {
    "k": (P.P_KP, "Kp", "mul", 1.1, 0.001, 15.9),
    "i": (P.P_KI, "Ki", "add", 0.5, 0.0, 15000.0),
    "d": (P.P_KD, "Kd", "add", 0.0002, 0.0, 0.0159),
    "l": (P.P_LATENCY, "L", "add", 1, 0, 127),
    "z": (P.P_DEADBAND, "zona morta", "add", 1, 0, 100),
    "g": (P.P_PLANT_GAIN, "ganho da planta", "mul", 1.02, 0.125, 8.0),
    "f": (P.P_D_SHIFT, "filtro D", "add", 1, 0, 8),
}

if sys.platform == "win32":
    import msvcrt

    def read_keys():
        keys = []
        while msvcrt.kbhit():
            c = msvcrt.getwch()
            if c in ("\x00", "\xe0"):       # tecla estendida: descarta o segundo codigo
                msvcrt.getwch()
            else:
                keys.append(c)
        return keys
else:
    def read_keys():
        return []


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", required=True, help="porta serial virtual (CDC) da Pico, ex.: COM5")
    ap.add_argument("--window", default=P.WINDOW_TITLE, help="titulo da janela a capturar")
    ap.add_argument("--roi", default="", help="left,top,width,height (em vez de --window)")
    ap.add_argument("--fps", type=float, default=60.0)
    ap.add_argument("--backend", choices=("auto", "dxcam", "mss"), default="auto")
    ap.add_argument("--mode", choices=tuple(MODES), default=None, help="modo inicial (padrao: nao altera)")
    ap.add_argument("--latency", type=int, default=None, help="L do estimador, em passos de 1 ms (0..127)")
    ap.add_argument("--deadband", type=int, default=None, help="zona morta [px]")
    ap.add_argument("--d-shift", type=int, default=None, help="filtro da derivada (0..8)")
    ap.add_argument("--id-amp", type=int, default=None, help="amplitude da identificacao [contagens]")
    ap.add_argument("--plant-gain", type=float, default=None, help="px por contagem (da identificacao)")
    ap.add_argument("--kp", type=float, default=None, help="[contagens/px]")
    ap.add_argument("--ki", type=float, default=None, help="[1/s]")
    ap.add_argument("--kd", type=float, default=None, help="[s]")
    ap.add_argument("--no-estimator", action="store_true")
    ap.add_argument("--log-prefix", default="", help="padrao: log_<data>")
    return ap.parse_args(argv)


def initial_params(a):
    """Lista (id, valor int32) pedida na linha de comando."""
    out = []
    for pid, val in ((P.P_KP, a.kp), (P.P_KI, a.ki), (P.P_KD, a.kd), (P.P_LATENCY, a.latency),
                     (P.P_DEADBAND, a.deadband), (P.P_D_SHIFT, a.d_shift), (P.P_ID_AMP, a.id_amp),
                     (P.P_PLANT_GAIN, a.plant_gain)):
        if val is not None:
            out.append((pid, P.to_raw(pid, val)))
    if a.no_estimator:
        out.append((P.P_EST_EN, 0))
    return out


def adjust(params, key, sign):
    """Novo valor (unidade fisica) do parametro da tecla 'key'; sign = +1 ou -1."""
    pid, _, kind, step, lo, hi = ADJUST[key]
    cur = params.get(P.PARAM_NAMES[pid - 1], 0.0)
    if kind == "mul":
        new = max(cur, lo) * (step if sign > 0 else 1.0 / step)
    else:
        new = cur + sign * step
    return pid, max(lo, min(hi, new))


def main(argv=None):
    a = parse_args(argv)
    winutil.set_dpi_aware()
    if a.roi:
        region = tuple(int(v) for v in a.roi.split(","))
    else:
        region = winutil.window_client_rect(a.window)
        if region is None:
            raise SystemExit(f"janela '{a.window}' nao encontrada: abra o testapp ou use --roi")
    grabber = Grabber(region, a.backend)
    # CDC: o baud e ignorado. Abrir a porta levanta o DTR, e o firmware so
    # envia telemetria com o DTR ativo.
    ser = serial.Serial(a.port, 115200, timeout=0, write_timeout=0.2)
    ser.reset_input_buffer()

    prefix = a.log_prefix or time.strftime("log_%Y%m%d_%H%M%S")
    f_tel = open(prefix + ".csv", "w", newline="")
    f_meas = open(prefix + "_meas.csv", "w", newline="")
    w_tel, w_meas = csv.writer(f_tel), csv.writer(f_meas)
    w_tel.writerow(("t",) + P.TELEM_FIELDS)
    w_meas.writerow(("t_capture", "seq", "valid", "ex", "ey", "target_x", "target_y", "cursor_x", "cursor_y"))
    print(f"captura: {grabber.backend} {region} | serial: {a.port} | log: {prefix}.csv")
    print("teclas: 0/1/2 modo | k i d l z g f seleciona, +/- ajusta | e estimador | s salva | o carrega | q sai")

    for pid, raw in initial_params(a):
        ser.write(P.pack_set_param(pid, raw))
    if a.mode is not None:
        ser.write(P.pack_set_mode(MODES[a.mode]))
    ser.write(P.pack_get_params())

    parser = P.FrameParser()
    params = {}                         # copia dos parametros do MCU, em unidade fisica
    selected, msg = "k", ""
    seq, period = 0, 1.0 / a.fps
    t0 = time.perf_counter()
    next_frame, next_print, last = t0, t0, None
    try:
        running = True
        while running:
            now = time.perf_counter()
            if now >= next_frame:
                next_frame = max(next_frame + period, now)
                img = grabber.grab()
                t_cap = time.perf_counter() - t0
                cx, cy = winutil.cursor_pos()
                pos = detect_target(img) if img is not None else None
                seq = (seq + 1) & 0xFF
                if pos is None:
                    ser.write(P.pack_meas(seq, 0, 0, valid=False))
                    w_meas.writerow((f"{t_cap:.4f}", seq, 0, 0, 0, "", "", cx, cy))
                else:
                    tx, ty = region[0] + pos[0], region[1] + pos[1]
                    ex, ey = round(tx - cx), round(ty - cy)
                    ser.write(P.pack_meas(seq, ex, ey, valid=True))
                    w_meas.writerow((f"{t_cap:.4f}", seq, 1, ex, ey, f"{tx:.1f}", f"{ty:.1f}", cx, cy))

            for key in read_keys():
                if key == "q":
                    running = False
                elif key in "012":
                    ser.write(P.pack_set_mode(int(key)))
                elif key in ADJUST:
                    selected = key
                elif key in "+=-_" and params:
                    pid, val = adjust(params, selected, +1 if key in "+=" else -1)
                    ser.write(P.pack_set_param(pid, P.to_raw(pid, val)) + P.pack_get_params())
                elif key == "e" and params:
                    ser.write(P.pack_set_param(P.P_EST_EN, 0 if params["est_en"] else 1) + P.pack_get_params())
                elif key == "s":
                    ser.write(P.pack_save())
                elif key == "o":
                    ser.write(P.pack_load() + P.pack_get_params())

            data = ser.read(4096)
            if data:
                t = time.perf_counter() - t0
                for ftype, payload in parser.feed(data):
                    if ftype == P.T_TELEM:
                        last = P.unpack_telem(payload)
                        w_tel.writerow([f"{t:.4f}"] + [last[c] for c in P.TELEM_FIELDS])
                    elif ftype == P.T_PARAMS:
                        params = P.unpack_params(payload)
                    elif ftype == P.T_ACK:
                        src, err = payload[0], payload[1]
                        if err != P.ERR_OK:
                            msg = f"NACK (tipo 0x{src:02X}): {P.ERR_NAMES[err] if err < len(P.ERR_NAMES) else err}"
                        elif src == P.T_SAVE:
                            msg = "parametros salvos na flash"
                        elif src == P.T_LOAD:
                            msg = "parametros carregados da flash"
                        else:
                            msg = ""
            if now >= next_print and last and params:
                next_print = now + 0.25
                state = P.STATE_NAMES[last["state"]] if last["state"] < len(P.STATE_NAMES) else "?"
                line = (f"\r{state:<13} hab={last['enabled']} link={last['link_ok']} "
                        f"e^=({last['eh_x']:+5d},{last['eh_y']:+5d}) "
                        f"Kp={params['kp']:.3f} Ki={params['ki']:.2f} Kd={params['kd']:.4f} "
                        f"L={params['latency']:.0f} zm={params['deadband']:.0f} g={params['plant_gain']:.2f} "
                        f"est={params['est_en']:.0f} [{ADJUST[selected][1]}] "
                        f"err={last['errs']} drop={last['hid_drop']} "
                        f"carga={last['load0']:.0f}/{last['load1']:.0f}% {msg}")
                print(line.ljust(150)[:150], end="", flush=True)
            time.sleep(0.0005)
    except KeyboardInterrupt:
        pass
    finally:
        f_tel.close()
        f_meas.close()
        ser.close()
        print(f"\nlogs: {prefix}.csv, {prefix}_meas.csv")


if __name__ == "__main__":
    main()
