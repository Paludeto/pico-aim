"""Aplicativo de teste 3D (Pygame): estande de tiro com alvo rastreavel e log CSV.

  python -m testapp --mode shooter              # modo shooter 3D com HP e respawn
  python -m testapp --mode step                 # trajetoria de ensaio para o tracker

Teclas na janela:
  1-4          degrau / rampa / senoide / aleatorio suave
  5            modo shooter 3D (bots com HP e respawn ao abater)
  Click/Espaco disparar
  F            liga/desliga auto-fire ao travar no alvo
  V            alterna visual 3D / classico 2D
  ESC          sai
"""
import argparse
import csv
import sys
import time

from common import protocol as P
from .trajectories import MODES, TrajConfig, Trajectory


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=MODES, default="step")
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--duration", type=float, default=0.0, help="segundos; 0 = ate fechar")
    ap.add_argument("--log", default="", help="CSV de saida (padrao: testapp_<data>.csv)")
    ap.add_argument("--period", type=float, default=2.0, help="degrau: intervalo entre saltos [s]")
    ap.add_argument("--step-size", type=float, default=0.0, help="degrau: vai e volta horizontal de N px (0 = aleatorio)")
    ap.add_argument("--speed", type=float, default=300.0, help="rampa [px/s]")
    ap.add_argument("--freq", type=float, default=0.5, help="senoide [Hz]")
    ap.add_argument("--amp", type=float, default=300.0, help="senoide [px]")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--classic", action="store_true", help="inicia na visualizacao 2D classica")
    ap.add_argument("--no-autofire", action="store_true", help="inicia com auto-fire desligado")
    a = ap.parse_args(argv)
    a.width, a.height = (int(v) for v in a.size.lower().split("x"))
    if not a.log:
        a.log = time.strftime("testapp_%Y%m%d_%H%M%S.csv")
    return a


def traj_config(a):
    return TrajConfig(a.width, a.height, 80, a.period, a.step_size, a.speed, a.freq, a.amp, a.seed)


class Logs:
    def __init__(self, path):
        self.f = open(path, "w", newline="")
        self.w = csv.writer(self.f)
        self.w.writerow(["t", "mode", "target_x", "target_y", "cursor_x", "cursor_y"])

    def frame(self, t, mode, target, cursor):
        self.w.writerow([f"{t:.4f}", mode, f"{target[0]:.1f}", f"{target[1]:.1f}",
                         f"{cursor[0]:.1f}", f"{cursor[1]:.1f}"])

    def close(self):
        self.f.close()


def _cursor_reader(pygame):
    """Posicao do cursor em coordenadas da janela."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        hwnd = pygame.display.get_wm_info()["window"]
        user32 = ctypes.windll.user32

        def read():
            pt = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            user32.ScreenToClient(hwnd, ctypes.byref(pt))
            return (pt.x, pt.y)
        return read
    return pygame.mouse.get_pos


def _draw_classic(pygame, screen, font, target, cursor, mode, t):
    screen.fill((16, 16, 20))
    pygame.draw.circle(screen, P.TARGET_COLOR, (round(target[0]), round(target[1])), P.TARGET_RADIUS)
    err = ((target[0] - cursor[0]) ** 2 + (target[1] - cursor[1]) ** 2) ** 0.5
    hud = f"modo: {mode}   erro: {err:6.1f} px   t: {t:6.1f} s   [1-5] modo  [V] 3D  [ESC] sair"
    screen.blit(font.render(hud, True, (150, 150, 160)), (10, 8))


def run_window(a):
    if sys.platform == "win32":             # coordenadas em pixels reais (sem escala de DPI)
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
    import pygame
    from .shooter3d import Shooter3DScene

    pygame.init()
    screen = pygame.display.set_mode((a.width, a.height))
    pygame.display.set_caption(P.WINDOW_TITLE)
    font = pygame.font.SysFont("consolas,dejavusansmono,monospace", 16)
    clock = pygame.time.Clock()
    read_cursor = _cursor_reader(pygame)

    mode = a.mode
    classic_view = a.classic
    traj = Trajectory(mode, traj_config(a))
    scene = Shooter3DScene(a.width, a.height, pygame, autofire=not a.no_autofire, seed=a.seed)
    scene.reset_shooter_bot()
    pygame.mouse.set_visible(classic_view)

    logs = Logs(a.log)
    t0 = time.perf_counter()
    prev_t = 0.0
    offset = 0.0
    mode_keys = (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5)
    running = True
    while running:
        manual_trigger = False
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT or (ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE):
                running = False
            elif ev.type == pygame.KEYDOWN and ev.key in mode_keys:
                idx = mode_keys.index(ev.key)
                if idx < len(MODES):
                    mode = MODES[idx]
                    traj = Trajectory(mode, traj_config(a))
                    offset = time.perf_counter() - t0       # a trajetoria nova comeca em t = 0
                    if mode == "shooter":
                        scene.reset_shooter_bot()
            elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_f:
                scene.autofire = not scene.autofire
            elif ev.type == pygame.KEYDOWN and ev.key == pygame.K_v:
                classic_view = not classic_view
                pygame.mouse.set_visible(classic_view)
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                manual_trigger = True

        t = time.perf_counter() - t0
        dt = max(1e-4, t - prev_t)
        prev_t = t
        if a.duration and t >= a.duration:
            break

        keys = pygame.key.get_pressed()
        mouse_btns = pygame.mouse.get_pressed()
        firing_manual = manual_trigger or bool(mouse_btns[0]) or bool(keys[pygame.K_SPACE])

        target = scene.shooter_target_pos(dt) if mode == "shooter" else traj.pos(t - offset)
        cursor = read_cursor()
        logs.frame(t, mode, target, cursor)

        if classic_view:
            _draw_classic(pygame, screen, font, target, cursor, mode, t)
        else:
            scene.update(dt, target, cursor, mode, firing_manual)
            scene.render(screen, target, cursor, mode, t)

        pygame.display.flip()
        clock.tick(60)
    logs.close()
    pygame.quit()
    return a.log


def main(argv=None):
    a = parse_args(argv)
    log = run_window(a)
    print(f"log: {log}")


if __name__ == "__main__":
    main()
