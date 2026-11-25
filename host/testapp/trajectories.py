"""Trajetorias do alvo: degrau, rampa, senoide, aleatorio suave e shooter."""
import math
import random
from dataclasses import dataclass

MODES = ("step", "ramp", "sine", "smooth", "shooter")


@dataclass
class TrajConfig:
    width: int = 1280
    height: int = 720
    margin: int = 80
    period: float = 2.0         # degrau: intervalo entre saltos [s]
    step_size: float = 0.0      # degrau: 0 = salto aleatorio; >0 = vai e volta horizontal [px]
    speed: float = 300.0        # rampa [px/s]
    freq: float = 0.5           # senoide [Hz]
    amp: float = 300.0          # senoide [px]
    seed: int = 1


class Trajectory:
    """pos(t) -> (x, y) em coordenadas da janela. Deterministica para um dado seed."""

    def __init__(self, mode: str, cfg: TrajConfig):
        if mode not in MODES:
            raise ValueError(f"modo desconhecido: {mode}")
        self.mode, self.cfg = mode, cfg
        self.rng = random.Random(cfg.seed)
        self.cx, self.cy = cfg.width / 2, cfg.height / 2
        self._step_idx = -1
        self._step_pos = (self.cx, self.cy)
        self._phases = [(self.rng.uniform(0, 2 * math.pi), self.rng.uniform(0, 2 * math.pi)) for _ in range(3)]

    def pos(self, t: float):
        c = self.cfg
        if self.mode == "step":
            idx = int(t / c.period)
            while self._step_idx < idx:
                self._step_idx += 1
                if c.step_size > 0:
                    sign = -1 if self._step_idx % 2 == 0 else 1
                    self._step_pos = (self.cx + sign * c.step_size / 2, self.cy)
                else:
                    self._step_pos = (self.rng.uniform(c.margin, c.width - c.margin),
                                      self.rng.uniform(c.margin, c.height - c.margin))
            return self._step_pos
        if self.mode == "ramp":                 # onda triangular: velocidade constante
            span = c.width - 2 * c.margin
            d = (c.speed * t) % (2 * span)
            return (c.margin + (d if d <= span else 2 * span - d), self.cy)
        if self.mode == "sine":
            return (self.cx + c.amp * math.sin(2 * math.pi * c.freq * t), self.cy)
        if self.mode == "shooter":
            # Movimento tatico de strafe + peeks suaves e deterministicos para f(t)
            mx = max(c.margin, 110)
            my = max(c.margin, 95)
            ax = max(40.0, c.width / 2 - mx)
            ay = max(40.0, c.height / 2 - my)
            p0, p1, p2 = self._phases
            # Strafe horizontal com rajadas de velocidade + variacao vertical de voo/peek
            sx = (0.58 * math.sin(2 * math.pi * 0.31 * t + p0[0])
                  + 0.28 * math.sin(2 * math.pi * 0.73 * t + p1[0])
                  + 0.14 * math.sin(2 * math.pi * 1.37 * t + p2[0]))
            sy = (0.48 * math.sin(2 * math.pi * 0.23 * t + p0[1])
                  + 0.32 * math.sin(2 * math.pi * 0.59 * t + p1[1])
                  + 0.20 * math.cos(2 * math.pi * 1.11 * t + p2[1]))
            x = max(mx, min(c.width - mx, self.cx + ax * sx))
            y = max(my, min(c.height - my, self.cy + ay * sy))
            return (x, y)
        # aleatorio suave: soma de senoides lentas com fases aleatorias
        ax, ay = (c.width / 2 - c.margin) / 1.75, (c.height / 2 - c.margin) / 1.75
        x = y = 0.0
        for i, (px, py) in enumerate(self._phases):
            f = 0.13 * (i + 1) * 1.37 ** i
            x += math.sin(2 * math.pi * f * t + px) / (i + 1)
            y += math.sin(2 * math.pi * f * 0.8 * t + py) / (i + 1)
        return (self.cx + ax * x, self.cy + ay * y)
