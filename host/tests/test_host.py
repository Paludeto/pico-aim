"""Testes do software do PC que nao dependem de hardware nem de janela aberta.

  python tests/test_host.py
"""
import os
import struct
import sys

import numpy as np

HOST_DIR = os.path.join(os.path.dirname(__file__), "..")
REPO_DIR = os.path.join(HOST_DIR, "..")
sys.path.insert(0, HOST_DIR)

from common import protocol as P                            # noqa: E402
from tracker.detect import detect_target                    # noqa: E402
from testapp.trajectories import MODES, TrajConfig, Trajectory  # noqa: E402
from analysis import metrics, identify                      # noqa: E402


def test_protocol():
    assert P.crc8(b"123456789") == 0xF4             # vetor de teste do CRC-8 (poli 0x07)
    f = P.pack_meas(7, -123, 456)
    assert len(f) == 11 and f[:4] == bytes([0xA5, 0x5A, 0x01, 0x06]) and P.crc8(f[2:10]) == f[10]
    assert P.pack_meas(1, 1e9, -1e9)[6:10] == bytes([0xFF, 0x7F, 0x00, 0x80])      # satura em int16

    # conversoes fisicas <-> Q16.16
    assert abs(P.from_raw(P.P_KP, P.to_raw(P.P_KP, 0.15)) - 0.15) < 1e-4
    assert abs(P.from_raw(P.P_KI, P.to_raw(P.P_KI, 3.0)) - 3.0) < 0.02
    assert abs(P.from_raw(P.P_KD, P.to_raw(P.P_KD, 0.002)) - 0.002) < 1e-5
    assert abs(P.from_raw(P.P_PLANT_GAIN, P.to_raw(P.P_PLANT_GAIN, 1.25)) - 1.25) < 1e-4

    # parser com lixo, quadro corrompido e fluxo fragmentado
    bad = f[:4] + bytes([20]) + f[5:]
    ack = P.frame(P.T_ACK, bytes([P.T_SET_PARAM, P.ERR_OK]))
    telem_payload = struct.pack("<IHBBhhhhhhHBBHH", 5000, 5, P.MODE_AUTO,
                                P.FL_ENABLED | P.FL_LINK_OK | P.FL_TARGET,
                                -12, 34, -5, 10, 2, -3, 1, 0, 4, 25, 8)
    telem = P.frame(P.T_TELEM, telem_payload)
    stream = bytes([0x00, 0xA5, 0x13]) + bad + ack + telem
    parser = P.FrameParser()
    frames = parser.feed(stream[:15]) + parser.feed(stream[15:])
    assert parser.crc_errors == 1
    assert len(frames) == 2 and frames[0][0] == P.T_ACK
    rows = P.telem_rows(frames)
    assert len(rows) == 1
    r = rows[0]
    assert (r["em_x"], r["em_y"], r["eh_x"], r["eh_y"], r["enabled"], r["link_ok"]) == (-12, 34, -5, 10, 1, 1)


def test_detect():
    img = np.full((300, 400, 3), 18, np.uint8)
    yy, xx = np.mgrid[:300, :400]
    img[(xx - 250) ** 2 + (yy - 120) ** 2 <= 18 ** 2] = (255, 0, 255)     # alvo (BGR)
    img[(xx - 40) ** 2 + (yy - 40) ** 2 <= 4 ** 2] = (255, 0, 255)        # ruido pequeno
    img[100:130, 240:252] = (255, 255, 255)                               # cursor por cima do alvo
    cx, cy = detect_target(img)
    assert abs(cx - 250) < 6 and abs(cy - 120) < 6, (cx, cy)
    assert detect_target(np.full((100, 100, 3), 18, np.uint8)) is None
    assert detect_target(np.full((100, 100, 3), 200, np.uint8)) is None


def test_trajectories():
    cfg = TrajConfig()
    for mode in MODES:
        tr = Trajectory(mode, cfg)
        pts = np.array([tr.pos(i / 60) for i in range(60 * 30)])
        assert pts[:, 0].min() >= 0 and pts[:, 0].max() <= cfg.width, mode
        assert pts[:, 1].min() >= 0 and pts[:, 1].max() <= cfg.height, mode
        again = Trajectory(mode, cfg)
        assert tuple(pts[-1]) == again.pos((60 * 30 - 1) / 60) or mode == "step"
    v = np.diff(np.array([Trajectory("ramp", cfg).pos(i / 60)[0] for i in range(600)])) * 60
    assert np.allclose(np.abs(v), cfg.speed, atol=cfg.speed * 0.01 + 1e-6) or (np.abs(np.abs(v) - cfg.speed) < 1).mean() > 0.97


def test_analysis_on_measurements():
    med_dir = os.path.join(REPO_DIR, "docs", "medicoes")
    r_step, _ = metrics.analyze(os.path.join(med_dir, "step_trim.csv"))
    assert r_step["overshoot"] < 10 and r_step["settle_max_ms"] < 250 and r_step["ss_err"] <= 2, r_step
    r_sine, _ = metrics.analyze(os.path.join(med_dir, "sine_trim.csv"))
    assert 0 < r_sine["rms"] < 100 and 10 < r_sine["delay_ms"] < 120, r_sine
    res = identify.identify(os.path.join(med_dir, "ident_telem.csv"))
    assert abs(res["x"]["gain"] - 1.25) < 0.05 and 2 <= res["x"]["L"] <= 20, res


def test_shooter3d_detection():
    """Garante que o cenario 3D nao gera falsos positivos e preserva o centroide do alvo."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame
    from testapp.shooter3d import Shooter3DScene

    pygame.init()
    try:
        w, h = 1280, 720
        surf = pygame.Surface((w, h))
        scene = Shooter3DScene(w, h, pygame, autofire=True, seed=7)
        cases = [
            ((640.0, 360.0), (640.0, 360.0), "step", True),
            ((90.0, 85.0), (300.0, 300.0), "step", True),        # proximo ao HUD superior esquerdo
            ((1185.0, 625.0), (1185.0, 625.0), "step", True),    # proximo a arma no canto inferior direito
            ((420.0, 220.0), (425.0, 218.0), "shooter", True),   # rajada com hitmarker/faiscas
            ((960.0, 150.0), (640.0, 360.0), "shooter", False),  # fora da mira
        ]
        for idx, (target, cursor, mode, firing) in enumerate(cases):
            t = (idx + 1) * 0.25
            for _ in range(3):
                scene.update(1 / 60.0, target, cursor, mode, firing)
            scene.render(surf, target, cursor, mode, t)
            rgb = pygame.surfarray.array3d(surf).transpose(1, 0, 2)
            bgr = np.ascontiguousarray(rgb[..., ::-1])
            det = detect_target(bgr)
            assert det is not None, f"alvo nao detectado no caso {idx}: {target}"
            err = ((det[0] - target[0]) ** 2 + (det[1] - target[1]) ** 2) ** 0.5
            assert err < 1.5, f"erro de centroide alto ({err:.2f} px) no caso {idx}: det={det}, target={target}"

            yy, xx = np.mgrid[:h, :w]
            masked = bgr.copy()
            masked[(xx - target[0]) ** 2 + (yy - target[1]) ** 2 <= (scene.target_radius + 3) ** 2] = (20, 20, 20)
            assert detect_target(masked) is None, f"falso positivo magenta no cenario 3D (caso {idx})"
    finally:
        pygame.quit()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
