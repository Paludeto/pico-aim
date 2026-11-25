"""Renderizador e simulacao de tiro 3D em Pygame para o app de teste.

Projetado para manter 100% de compatibilidade com o rastreador visual (tracker):
- O nucleo magenta (P.TARGET_COLOR) fica sempre centralizado exatamente em
  (target_x, target_y) em coordenadas da janela e nunca e ocluido pelo cenario
  nem pela arma.
- Nenhuma outra cor da cena, HUD ou efeitos cai na faixa HSV/RGB do magenta
  detectada por host/tracker/detect.py.
"""
import math
import random
from dataclasses import dataclass

from common import protocol as P

# Paleta tatica estritamente livre de magenta/roxo/rosa (H fora de 135..170)
SKY_TOP = (8, 13, 24)
SKY_HORIZON = (22, 35, 54)
FOG_COLOR = (17, 27, 42)
FLOOR_DARK = (20, 29, 41)
FLOOR_ALT = (25, 36, 50)
FLOOR_GRID = (44, 98, 128)
LANE_LINE = (58, 152, 184)
WALL_LOWER = (30, 40, 54)
WALL_UPPER = (38, 50, 66)
PILLAR_COLOR = (54, 70, 90)
CEILING_BEAM = (28, 38, 52)
LIGHT_CYAN = (72, 224, 248)
LIGHT_EMERALD = (62, 236, 146)
LIGHT_AMBER = (248, 190, 56)
WARN_ORANGE = (242, 82, 38)
STEEL_LIGHT = (142, 162, 182)
STEEL_MID = (86, 102, 120)
STEEL_DARK = (44, 54, 68)
HUD_BG = (10, 16, 26, 188)
HUD_BORDER = (58, 142, 174)
HUD_TEXT = (222, 236, 246)
HUD_MUTED = (132, 154, 174)

# Tons do nucleo do alvo: todos dentro de HSV [140..165, 120..255, 120..255]
# e da mascara fallback (R > 180, B > 180, G < 90).
CORE_RIM = (210, 0, 210)
CORE_MAIN = P.TARGET_COLOR       # (255, 0, 255)
CORE_SPEC = (255, 52, 255)

MODE_LABELS = {
    "step": "DEGRAU",
    "ramp": "RAMPA",
    "sine": "SENOIDE",
    "smooth": "ALEATORIO",
    "shooter": "SHOOTER 3D",
    "ident": "IDENTIFICACAO",
}

LIGHT_DIR = (-0.36, 0.84, -0.40)


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _lerp(a, b, t):
    return a + (b - a) * t


def _lerp_rgb(c1, c2, t):
    t = _clamp(t, 0.0, 1.0)
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def _shade_rgb(rgb, factor):
    return (
        int(_clamp(rgb[0] * factor, 0, 255)),
        int(_clamp(rgb[1] * factor, 0, 255)),
        int(_clamp(rgb[2] * factor, 0, 255)),
    )


def _apply_fog(rgb, z, z_start=14.0, z_end=58.0):
    if z <= z_start:
        return rgb
    f = _clamp((z - z_start) / (z_end - z_start), 0.0, 0.88)
    return _lerp_rgb(rgb, FOG_COLOR, f)


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(v):
    ln = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (0.0, 1.0, 0.0) if ln < 1e-9 else (v[0] / ln, v[1] / ln, v[2] / ln)


class Camera3D:
    """Camera em perspectiva com paralaxe suave e projecao/desprojecao exatas."""

    def __init__(self, width: int, height: int, fov_deg: float = 70.0):
        self.w = width
        self.h = height
        self.cx = width * 0.5
        self.cy = height * 0.5
        self.f = (width * 0.5) / math.tan(math.radians(fov_deg * 0.5))
        self.near = 0.6
        self.pos = [0.0, 2.0, 0.0]
        self.yaw = 0.0
        self.pitch = 0.0
        self._cy = 1.0
        self._sy = 0.0
        self._cp = 1.0
        self._sp = 0.0

    def set_pose(self, x: float, y: float, z: float, yaw: float, pitch: float):
        self.pos[0], self.pos[1], self.pos[2] = x, y, z
        self.yaw, self.pitch = yaw, pitch
        self._cy, self._sy = math.cos(yaw), math.sin(yaw)
        self._cp, self._sp = math.cos(pitch), math.sin(pitch)

    def world_to_cam(self, p):
        dx = p[0] - self.pos[0]
        dy = p[1] - self.pos[1]
        dz = p[2] - self.pos[2]
        x1 = dx * self._cy - dz * self._sy
        z1 = dx * self._sy + dz * self._cy
        y2 = dy * self._cp - z1 * self._sp
        z2 = dy * self._sp + z1 * self._cp
        return (x1, y2, z2)

    def project_cam(self, pc):
        z = pc[2]
        if z <= 1e-4:
            return None
        inv_z = self.f / z
        return (self.cx + pc[0] * inv_z, self.cy - pc[1] * inv_z)

    def project(self, p):
        pc = self.world_to_cam(p)
        if pc[2] < self.near:
            return None
        return self.project_cam(pc)

    def screen_to_world(self, sx: float, sy: float, z_cam: float):
        """Retorna ponto 3D no mundo que projeta exatamente para (sx, sy) a profundidade z_cam."""
        x1 = (sx - self.cx) * z_cam / self.f
        y2 = -(sy - self.cy) * z_cam / self.f
        dy = y2 * self._cp + z_cam * self._sp
        z1 = -y2 * self._sp + z_cam * self._cp
        dx = x1 * self._cy + z1 * self._sy
        dz = -x1 * self._sy + z1 * self._cy
        return (self.pos[0] + dx, self.pos[1] + dy, self.pos[2] + dz)

    def clip_poly_near(self, cam_pts):
        """Recorta poligono no espaco da camera contra o plano z >= near."""
        if not cam_pts:
            return []
        out = []
        n = len(cam_pts)
        near = self.near
        for i in range(n):
            a = cam_pts[i]
            b = cam_pts[(i + 1) % n]
            a_in = a[2] >= near
            b_in = b[2] >= near
            if a_in and b_in:
                out.append(b)
            elif a_in and not b_in:
                t = (near - a[2]) / (b[2] - a[2])
                out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, near))
            elif not a_in and b_in:
                t = (near - a[2]) / (b[2] - a[2])
                out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, near))
                out.append(b)
        return out

    def clip_segment_near(self, a, b):
        near = self.near
        a_in = a[2] >= near
        b_in = b[2] >= near
        if not a_in and not b_in:
            return None
        if a_in and b_in:
            return a, b
        t = (near - a[2]) / (b[2] - a[2])
        mid = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, near)
        return (a, mid) if a_in else (mid, b)


def _rot_xyz(x, y, z, roll=0.0, pitch=0.0, yaw=0.0):
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cyw, syw = math.cos(yaw), math.sin(yaw)
    x1 = x * cr - y * sr
    y1 = x * sr + y * cr
    y2 = y1 * cp - z * sp
    z2 = y1 * sp + z * cp
    x3 = x1 * cyw + z2 * syw
    z3 = -x1 * syw + z2 * cyw
    return (x3, y2, z3)


def _box_faces(cx, cy, cz, sx, sy, sz, color, roll=0.0, pitch=0.0, yaw=0.0, outline=None,
               pivot=None, local_offset=(0.0, 0.0, 0.0)):
    """Gera faces de um paralelepipedo 3D (suporta corpo rigido com pivot unico)."""
    hx, hy, hz = sx * 0.5, sy * 0.5, sz * 0.5
    ox, oy, oz = local_offset
    local = [
        (ox - hx, oy - hy, oz - hz), (ox + hx, oy - hy, oz - hz),
        (ox + hx, oy + hy, oz - hz), (ox - hx, oy + hy, oz - hz),
        (ox - hx, oy - hy, oz + hz), (ox + hx, oy - hy, oz + hz),
        (ox + hx, oy + hy, oz + hz), (ox - hx, oy + hy, oz + hz),
    ]
    px, py, pz = pivot if pivot is not None else (cx, cy, cz)
    verts = []
    for x, y, z in local:
        rx, ry, rz = _rot_xyz(x, y, z, roll=roll, pitch=pitch, yaw=yaw)
        verts.append((px + rx, py + ry, pz + rz))

    # Indices em ordem CCW vistos de fora
    idx_faces = (
        (0, 3, 2, 1),   # frente (-Z, voltada para a camera)
        (4, 5, 6, 7),   # traseira (+Z)
        (0, 4, 7, 3),   # esquerda (-X)
        (1, 2, 6, 5),   # direita (+X)
        (3, 7, 6, 2),   # topo (+Y)
        (0, 1, 5, 4),   # base (-Y)
    )
    out = []
    for f in idx_faces:
        pts = [verts[i] for i in f]
        n = _norm(_cross(_sub(pts[1], pts[0]), _sub(pts[2], pts[0])))
        out.append((pts, n, color, outline))
    return out


@dataclass
class Spark:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    color: tuple
    size: float


@dataclass
class Tracer:
    x0: float
    y0: float
    x1: float
    y1: float
    life: float
    max_life: float
    hit: bool


@dataclass
class Shell:
    x: float
    y: float
    vx: float
    vy: float
    angle: float
    v_ang: float
    life: float


@dataclass
class FloatingText:
    x: float
    y: float
    text: str
    color: tuple
    life: float
    max_life: float


class Shooter3DScene:
    """Cena completa de shooter 3D com arena, robo-alvo, arma em 1a pessoa e HUD."""

    def __init__(self, width: int, height: int, pygame, autofire: bool = True, seed: int = 1):
        self.w = width
        self.h = height
        self.pg = pygame
        self.cam = Camera3D(width, height, fov_deg=68.0)
        self.autofire = autofire
        self.rng = random.Random(seed + 1337)

        # Fontes
        self.font_lg = pygame.font.SysFont("consolas,dejavusansmono,monospace", 20, bold=True)
        self.font_md = pygame.font.SysFont("consolas,dejavusansmono,monospace", 15, bold=True)
        self.font_sm = pygame.font.SysFont("consolas,dejavusansmono,monospace", 13)
        self.font_xs = pygame.font.SysFont("consolas,dejavusansmono,monospace", 11)

        # Ceu / horizonte pre-renderizado para desempenho a 60 FPS
        self._sky = self._build_sky_surface()
        self._skyline = self._build_skyline()
        self._props = self._build_arena_props()
        self._hud_tl = pygame.Surface((290, 96), pygame.SRCALPHA)
        self._hud_tr = pygame.Surface((250, 96), pygame.SRCALPHA)
        self._radar_surf = pygame.Surface((132, 118), pygame.SRCALPHA)

        # Estado dinamico da camera / arma / alvo
        self.cam_yaw = 0.0
        self.cam_pitch = 0.0
        self.cam_lean = 0.0
        self.recoil = 0.0
        self.muzzle_flash = 0.0
        self.hitmarker = 0.0
        self.bot_flash = 0.0
        self.bot_recoil = 0.0
        self.fire_cd = 0.0

        self.prev_target = None
        self.bot_vx = 0.0
        self.bot_vy = 0.0
        self.bot_hp = 100
        self.bot_max_hp = 100
        self.target_radius = P.TARGET_RADIUS

        # Estatisticas de combate / rastreamento
        self.score = 0
        self.kills = 0
        self.streak = 0
        self.shots = 0
        self.hits = 0
        self.lock_frames = 0
        self.total_frames = 0
        self.kill_banner = ""
        self.kill_banner_t = 0.0

        # Respawn dinamico no modo shooter
        self._shooter_anchor = [width * 0.5, height * 0.48]
        self._shooter_phase = [0.0, 0.0]
        self._shooter_z = 20.0
        self._cur_z_bot = 20.0
        self._shooter_t = 0.0

        # Particulas e efeitos
        self.sparks = []
        self.tracers = []
        self.shells = []
        self.popups = []

        # Ponto de saida da arma (atualizado ao desenhar o viewmodel)
        self._muzzle_screen = (int(width * 0.78), int(height * 0.78))

    def _build_sky_surface(self):
        surf = self.pg.Surface((self.w, self.h))
        horizon = int(self.h * 0.56)
        for y in range(self.h):
            if y < horizon:
                t = (y / max(1, horizon)) ** 1.35
                col = _lerp_rgb(SKY_TOP, SKY_HORIZON, t)
            else:
                t = (y - horizon) / max(1, self.h - horizon)
                col = _lerp_rgb(FOG_COLOR, (11, 17, 26), t)
            self.pg.draw.line(surf, col, (0, y), (self.w, y))
        # Estrelas sutis / luzes distantes no topo
        star_rng = random.Random(42)
        for _ in range(42):
            sx = star_rng.randint(0, self.w - 1)
            sy = star_rng.randint(4, int(self.h * 0.36))
            b = star_rng.randint(65, 130)
            surf.set_at((sx, sy), (b, b + 16, min(255, b + 36)))
        return surf

    def _build_skyline(self):
        rng = random.Random(99)
        towers = []
        x = -120
        while x < self.w + 180:
            tw = rng.randint(36, 95)
            th = rng.randint(45, 155)
            windows = []
            for wy in range(10, th - 14, 14):
                for wx in range(6, tw - 8, 12):
                    if rng.random() < 0.28:
                        col = LIGHT_CYAN if rng.random() < 0.6 else LIGHT_AMBER
                        windows.append((wx, wy, _shade_rgb(col, 0.35)))
            towers.append((x, tw, th, windows))
            x += tw + rng.randint(4, 18)
        return towers

    def _build_arena_props(self):
        # Caixas taticas e barreiras ao longo das laterais e fundo da arena
        props = []
        specs = [
            (-11.2, 1.1, 16.0, 2.4, 2.2, 2.4, (44, 58, 72)),
            (11.4, 0.95, 22.0, 2.2, 1.9, 2.6, (42, 56, 70)),
            (-10.5, 1.4, 34.0, 3.0, 2.8, 2.8, (40, 52, 66)),
            (10.6, 1.25, 38.0, 2.8, 2.5, 3.0, (44, 56, 70)),
            (-5.5, 0.75, 45.0, 3.8, 1.5, 1.4, (50, 62, 76)),
            (5.5, 0.75, 45.0, 3.8, 1.5, 1.4, (50, 62, 76)),
        ]
        for cx, cy, cz, sx, sy, sz, col in specs:
            props.extend(_box_faces(cx, cy, cz, sx, sy, sz, col, outline=(62, 86, 108)))
        return props

    def reset_shooter_bot(self, avoid=None):
        """Reposiciona o alvo no modo shooter apos eliminacao."""
        mx = max(125, int(self.w * 0.14))
        my = max(105, int(self.h * 0.17))
        best = None
        for _ in range(8):
            nx = self.rng.uniform(mx, self.w - mx)
            ny = self.rng.uniform(my, self.h - my - 30)
            if avoid is None or math.hypot(nx - avoid[0], ny - avoid[1]) > min(self.w, self.h) * 0.25:
                best = (nx, ny)
                break
        if best is None:
            best = (self.w * 0.5, self.h * 0.45)
        self._shooter_anchor[0], self._shooter_anchor[1] = best
        self._shooter_phase = [self.rng.uniform(0, 2 * math.pi), self.rng.uniform(0, 2 * math.pi)]
        self._shooter_z = self.rng.uniform(15.5, 25.5)
        self._shooter_t = 0.0
        self.bot_hp = self.bot_max_hp

    def shooter_target_pos(self, dt: float):
        """Posicao do alvo no modo shooter interativo (com strafe e respawn ao abater)."""
        self._shooter_t += dt
        t = self._shooter_t
        ax = min(145.0, self.w * 0.12)
        ay = min(68.0, self.h * 0.09)
        x = self._shooter_anchor[0] + ax * math.sin(2.1 * t + self._shooter_phase[0])
        y = self._shooter_anchor[1] + ay * math.sin(1.45 * t + self._shooter_phase[1])
        mx, my = 100.0, 90.0
        x = _clamp(x, mx, self.w - mx)
        y = _clamp(y, my, self.h - my)
        return (x, y)

    def _spawn_sparks(self, sx, sy, count, hit_target=False, radius_clear=0.0, big=False):
        for _ in range(count):
            ang = self.rng.uniform(0, 2 * math.pi)
            spd = self.rng.uniform(110, 420 if big else 280)
            start_r = radius_clear + (self.rng.uniform(2, 8) if hit_target else 0.0)
            x = sx + math.cos(ang) * start_r
            y = sy + math.sin(ang) * start_r
            vx = math.cos(ang) * spd
            vy = math.sin(ang) * spd - (60 if big else 30)
            col = self.rng.choice((LIGHT_AMBER, (255, 232, 130), LIGHT_CYAN, WARN_ORANGE))
            life = self.rng.uniform(0.18, 0.55 if big else 0.34)
            self.sparks.append(Spark(x, y, vx, vy, life, life, col, self.rng.uniform(2.0, 4.5 if big else 3.2)))

    def fire_shot(self, cursor, target, mode: str):
        """Dispara a arma em direcao ao cursor e computa acerto no alvo."""
        if self.fire_cd > 0.0:
            return False
        self.fire_cd = 0.105        # ~9.5 disparos/s
        self.shots += 1
        self.recoil = min(1.0, self.recoil + 0.55)
        self.muzzle_flash = 0.055

        cx, cy = cursor
        tx, ty = target
        dist = math.hypot(tx - cx, ty - cy)
        hit_r = self.target_radius + 6.0
        hit = dist <= hit_r

        # Ponto final do tracer: para antes do nucleo magenta para nao ocluir o alvo
        mx, my = self._muzzle_screen
        ex, ey = cx, cy
        if hit and dist < self.target_radius + 4:
            dx, dy = mx - tx, my - ty
            ln = math.hypot(dx, dy) or 1.0
            ex = tx + (dx / ln) * (self.target_radius + 5)
            ey = ty + (dy / ln) * (self.target_radius + 5)
        self.tracers.append(Tracer(mx, my, ex, ey, 0.085, 0.085, hit))

        # Estojo de municao ejetado para a direita
        self.shells.append(Shell(
            mx + 18, my + 12,
            self.rng.uniform(110, 190), self.rng.uniform(-220, -140),
            self.rng.uniform(0, 6.28), self.rng.uniform(8, 16), 0.65,
        ))

        if hit:
            self.hits += 1
            self.hitmarker = 0.13
            self.bot_flash = 0.095
            self.bot_recoil = min(1.0, self.bot_recoil + 0.75)
            crit = dist <= self.target_radius * 0.55
            dmg = 34 if crit else 22
            self.bot_hp -= dmg
            self.score += 25 if crit else 15
            self._spawn_sparks(tx, ty, 9, hit_target=True, radius_clear=self.target_radius + 5)
            self.popups.append(FloatingText(
                tx + self.rng.uniform(-26, 26), ty - self.target_radius * 3.1 - self.rng.uniform(4, 14),
                f"+{dmg} CRIT" if crit else f"+{dmg}",
                LIGHT_AMBER if crit else LIGHT_CYAN, 0.55, 0.55,
            ))
            if self.bot_hp <= 0:
                self.kills += 1
                self.streak += 1
                self.score += 100 + min(self.streak, 10) * 20
                self._spawn_sparks(tx, ty, 24, hit_target=True, radius_clear=self.target_radius + 6, big=True)
                if mode == "shooter":
                    self.kill_banner = f"ALVO ELIMINADO  x{self.streak}"
                    self.kill_banner_t = 1.15
                    self.reset_shooter_bot(avoid=(tx, ty))
                else:
                    # Nos modos de benchmark a trajetoria nao muda: recarrega escudo do robo
                    self.bot_hp = self.bot_max_hp
                    self.kill_banner = f"ESCUDO QUEBRADO  x{self.streak}"
                    self.kill_banner_t = 0.85
        else:
            self._spawn_sparks(cx, cy, 4, hit_target=False)
        return hit

    def update(self, dt: float, target, cursor, mode: str, firing_manual: bool):
        dt = min(dt, 0.05)
        self.total_frames += 1

        # Velocidade do alvo para inclinar (bank) o robo 3D
        if self.prev_target is not None and dt > 1e-4:
            vx = (target[0] - self.prev_target[0]) / dt
            vy = (target[1] - self.prev_target[1]) / dt
            # Ignora saltos bruscos de degrau para nao dar "chute" exagerado
            if math.hypot(vx, vy) > 2200:
                vx, vy = 0.0, 0.0
            self.bot_vx = _lerp(self.bot_vx, vx, min(1.0, dt * 10.0))
            self.bot_vy = _lerp(self.bot_vy, vy, min(1.0, dt * 10.0))
        self.prev_target = (target[0], target[1])

        # Paralaxe 3D suave acompanhando o cursor
        nx = _clamp((cursor[0] - self.w * 0.5) / (self.w * 0.5), -1.0, 1.0)
        ny = _clamp((cursor[1] - self.h * 0.5) / (self.h * 0.5), -1.0, 1.0)
        self.cam_yaw = _lerp(self.cam_yaw, nx * 0.095, min(1.0, dt * 9.0))
        self.cam_pitch = _lerp(self.cam_pitch, -ny * 0.060, min(1.0, dt * 9.0))
        self.cam_lean = _lerp(self.cam_lean, nx * 0.42, min(1.0, dt * 8.0))

        # Decaimentos
        self.recoil = max(0.0, self.recoil - dt * 5.2)
        self.muzzle_flash = max(0.0, self.muzzle_flash - dt)
        self.hitmarker = max(0.0, self.hitmarker - dt)
        self.bot_flash = max(0.0, self.bot_flash - dt)
        self.bot_recoil = max(0.0, self.bot_recoil - dt * 5.0)
        self.fire_cd = max(0.0, self.fire_cd - dt)
        self.kill_banner_t = max(0.0, self.kill_banner_t - dt)

        # Profundidade e raio do nucleo (fixo = P.TARGET_RADIUS nos modos de benchmark)
        if mode == "shooter":
            z_bot = self._shooter_z + 1.8 * math.sin(self._shooter_t * 1.1)
            self.target_radius = int(_clamp(round(P.TARGET_RADIUS * (20.0 / z_bot)), 15, 22))
        else:
            z_bot = 20.0
            self.target_radius = P.TARGET_RADIUS
        self._cur_z_bot = z_bot

        # Lock-on e disparo automatico (ou manual)
        err = math.hypot(target[0] - cursor[0], target[1] - cursor[1])
        locked = err <= self.target_radius + 4.0
        if locked:
            self.lock_frames += 1
        if firing_manual or (self.autofire and locked):
            self.fire_shot(cursor, target, mode)

        # Atualiza particulas
        alive_sparks = []
        for s in self.sparks:
            s.life -= dt
            if s.life > 0:
                s.x += s.vx * dt
                s.y += s.vy * dt
                s.vy += 460.0 * dt
                s.vx *= (1.0 - min(0.5, dt * 2.5))
                alive_sparks.append(s)
        self.sparks = alive_sparks

        alive_tracers = []
        for tr in self.tracers:
            tr.life -= dt
            if tr.life > 0:
                alive_tracers.append(tr)
        self.tracers = alive_tracers
        alive_shells = []
        for sh in self.shells:
            sh.life -= dt
            if sh.life > 0:
                sh.x += sh.vx * dt
                sh.y += sh.vy * dt
                sh.vy += 760.0 * dt
                sh.angle += sh.v_ang * dt
                alive_shells.append(sh)
        self.shells = alive_shells

        alive_pop = []
        for pop in self.popups:
            pop.life -= dt
            if pop.life > 0:
                pop.y -= 36.0 * dt
                alive_pop.append(pop)
        self.popups = alive_pop

        # Pose final da camera com leve recuo vertical
        self.cam.set_pose(
            self.cam_lean,
            2.15 + self.recoil * 0.03,
            0.0,
            self.cam_yaw,
            self.cam_pitch + self.recoil * 0.014,
        )

    def _draw_world_poly(self, screen, world_pts, color, outline=None, outline_w=1):
        cam_pts = [self.cam.world_to_cam(p) for p in world_pts]
        clipped = self.cam.clip_poly_near(cam_pts)
        if len(clipped) < 3:
            return
        pts2d = [self.cam.project_cam(p) for p in clipped]
        self.pg.draw.polygon(screen, color, pts2d)
        if outline is not None:
            self.pg.draw.polygon(screen, outline, pts2d, outline_w)

    def _draw_world_line(self, screen, p0, p1, color, width=1):
        seg = self.cam.clip_segment_near(self.cam.world_to_cam(p0), self.cam.world_to_cam(p1))
        if seg is None:
            return
        a = self.cam.project_cam(seg[0])
        b = self.cam.project_cam(seg[1])
        self.pg.draw.line(screen, color, a, b, width)

    def _draw_arena(self, screen):
        pg = self.pg
        screen.blit(self._sky, (0, 0))

        # Horizonte / skyline distante deslocado pela paralaxe
        horizon_y = int(self.h * 0.56 + self.cam.pitch * self.cam.f * 0.65)
        shift_x = int(-self.cam.yaw * self.cam.f * 0.55)
        for tx, tw, th, wins in self._skyline:
            rx = tx + shift_x
            if rx + tw < 0 or rx > self.w:
                continue
            ry = horizon_y - th
            pg.draw.rect(screen, (14, 22, 35), (rx, ry, tw, th + 30))
            for wx, wy, wc in wins:
                pg.draw.rect(screen, wc, (rx + wx, ry + wy, 4, 6))

        # Chao 3D em faixas de profundidade
        half_w = 15.0
        z_strips = [2.0, 7.0, 12.0, 17.0, 22.0, 28.0, 35.0, 43.0, 52.0]
        for i in range(len(z_strips) - 1):
            z0, z1 = z_strips[i], z_strips[i + 1]
            zm = (z0 + z1) * 0.5
            base = FLOOR_DARK if i % 2 == 0 else FLOOR_ALT
            col = _apply_fog(base, zm)
            self._draw_world_poly(
                screen,
                [(-half_w, 0.0, z0), (half_w, 0.0, z0), (half_w, 0.0, z1), (-half_w, 0.0, z1)],
                col,
            )

        # Paredes laterais 3D (inferior + superior)
        wall_h_mid = 3.2
        wall_h_top = 10.6
        for side in (-1.0, 1.0):
            wx = side * half_w
            for i in range(len(z_strips) - 1):
                z0, z1 = z_strips[i], z_strips[i + 1]
                zm = (z0 + z1) * 0.5
                c_lo = _apply_fog(WALL_LOWER, zm)
                c_hi = _apply_fog(WALL_UPPER, zm)
                self._draw_world_poly(screen, [(wx, 0.0, z0), (wx, 0.0, z1), (wx, wall_h_mid, z1), (wx, wall_h_mid, z0)], c_lo)
                self._draw_world_poly(screen, [(wx, wall_h_mid, z0), (wx, wall_h_mid, z1), (wx, wall_h_top, z1), (wx, wall_h_top, z0)], c_hi)

        # Parede de fundo do estande (z = 52)
        back_z = 52.0
        self._draw_world_poly(
            screen,
            [(-half_w, 0.0, back_z), (half_w, 0.0, back_z), (half_w, wall_h_top, back_z), (-half_w, wall_h_top, back_z)],
            _apply_fog((26, 38, 54), back_z),
            outline=_apply_fog((54, 118, 148), back_z),
        )
        # Moldura iluminada na parede do fundo + marca tatica do estande
        self._draw_world_poly(
            screen,
            [(-9.5, 2.2, back_z - 0.1), (9.5, 2.2, back_z - 0.1), (9.5, 7.6, back_z - 0.1), (-9.5, 7.6, back_z - 0.1)],
            _apply_fog((18, 28, 42), back_z),
            outline=_apply_fog(LANE_LINE, back_z),
            outline_w=2,
        )
        self._draw_world_line(screen, (-8.8, 4.9, back_z - 0.12), (8.8, 4.9, back_z - 0.12), _apply_fog(FLOOR_GRID, back_z), 1)
        self._draw_world_line(screen, (0.0, 2.5, back_z - 0.12), (0.0, 7.3, back_z - 0.12), _apply_fog(FLOOR_GRID, back_z), 1)
        sign_pt = self.cam.project((0.0, 7.95, back_z - 0.15))
        if sign_pt:
            sign = self.font_xs.render("ESTANDE RP2040 // SETOR 07", True, _apply_fog(LIGHT_CYAN, 34.0))
            screen.blit(sign, (int(sign_pt[0]) - sign.get_width() // 2, int(sign_pt[1]) - sign.get_height() // 2))

        # Grade em perspectiva no chao + faixas laterais de alerta
        for gx in (-12.0, -8.0, -4.0, 0.0, 4.0, 8.0, 12.0):
            col = LANE_LINE if gx in (-4.0, 4.0) else FLOOR_GRID
            self._draw_world_line(screen, (gx, 0.01, 2.0), (gx, 0.01, back_z), _apply_fog(col, 24.0), 1)
        for gz in (6.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 46.0):
            col = _apply_fog(LANE_LINE if gz % 10 == 0 else FLOOR_GRID, gz)
            self._draw_world_line(screen, (-half_w, 0.01, gz), (half_w, 0.01, gz), col, 1)
            if gz in (10.0, 20.0, 30.0, 40.0):
                pt = self.cam.project((-12.6, 0.05, gz))
                if pt and 0 <= pt[0] <= self.w and 0 <= pt[1] <= self.h:
                    lbl = self.font_xs.render(f"{int(gz)}M", True, _apply_fog(LIGHT_CYAN, gz))
                    screen.blit(lbl, (int(pt[0]), int(pt[1]) - 12))

        # Guias ambar nas bordas do chao
        for side in (-1.0, 1.0):
            self._draw_world_line(screen, (side * 14.2, 0.03, 2.0), (side * 14.2, 0.03, back_z), _apply_fog(LIGHT_AMBER, 26.0), 2)

        # Pilares estruturais e vigas de teto a cada 10m
        for pz in (10.0, 20.0, 30.0, 40.0, 50.0):
            pcol = _apply_fog(PILLAR_COLOR, pz)
            lcol = _apply_fog(LIGHT_CYAN, pz)
            bcol = _apply_fog(CEILING_BEAM, pz)
            # Viga superior
            self._draw_world_poly(
                screen,
                [(-half_w, wall_h_top - 0.7, pz), (half_w, wall_h_top - 0.7, pz),
                 (half_w, wall_h_top, pz), (-half_w, wall_h_top, pz)],
                bcol,
            )
            # Luminaria de teto
            self._draw_world_line(screen, (-4.5, wall_h_top - 0.75, pz), (4.5, wall_h_top - 0.75, pz), lcol, 3)
            # Pilares esquerdo e direito + fita ciano
            for side in (-1.0, 1.0):
                x0 = side * half_w
                x1 = side * (half_w - 1.15)
                self._draw_world_poly(
                    screen,
                    [(x0, 0.0, pz), (x1, 0.0, pz), (x1, wall_h_top, pz), (x0, wall_h_top, pz)],
                    pcol,
                )
                self._draw_world_line(screen, (x1, 0.5, pz - 0.05), (x1, wall_h_mid + 2.2, pz - 0.05), lcol, 2)

        # Caixas taticas e barreiras 3D (ordenadas do fundo para frente)
        self._draw_faces_sorted(screen, self._props)

    def _draw_faces_sorted(self, screen, faces, extra_flash=0.0):
        render_list = []
        cam_pos = self.cam.pos
        for pts, normal, base_col, outline in faces:
            # Back-face culling usando vetor do centro da face ate a camera
            cx = (pts[0][0] + pts[1][0] + pts[2][0] + pts[3][0]) * 0.25
            cy = (pts[0][1] + pts[1][1] + pts[2][1] + pts[3][1]) * 0.25
            cz = (pts[0][2] + pts[1][2] + pts[2][2] + pts[3][2]) * 0.25
            to_cam = (cam_pos[0] - cx, cam_pos[1] - cy, cam_pos[2] - cz)
            if _dot(normal, to_cam) <= 0.0:
                continue
            cam_pts = [self.cam.world_to_cam(p) for p in pts]
            clipped = self.cam.clip_poly_near(cam_pts)
            if len(clipped) < 3:
                continue
            avg_z = sum(p[2] for p in clipped) / len(clipped)
            # Iluminacao direcional + ambiente
            ndotl = max(0.0, _dot(normal, LIGHT_DIR))
            shade = 0.52 + 0.58 * ndotl
            col = _shade_rgb(base_col, shade)
            if extra_flash > 0.0:
                col = _lerp_rgb(col, (255, 228, 155), extra_flash * 0.72)
            col = _apply_fog(col, avg_z)
            out_col = _apply_fog(outline, avg_z) if outline else None
            pts2d = [self.cam.project_cam(p) for p in clipped]
            render_list.append((avg_z, pts2d, col, out_col))

        render_list.sort(key=lambda item: item[0], reverse=True)
        for _, pts2d, col, out_col in render_list:
            self.pg.draw.polygon(screen, col, pts2d)
            if out_col is not None:
                self.pg.draw.polygon(screen, out_col, pts2d, 1)

    def _draw_bot_body(self, screen, target, t_now: float):
        """Desenha o robo-alvo 3D blindado (sem o nucleo magenta, que e desenhado depois)."""
        pg = self.pg
        tx, ty = target
        z_bot = self._cur_z_bot
        # Posicao 3D exata cuja projecao cai em (tx, ty)
        wx, wy, wz = self.cam.screen_to_world(tx, ty, z_bot)
        self._bot_world = (wx, wy, wz)

        # Escala fisica consistente com o raio do nucleo na tela
        r_world = (self.target_radius * z_bot) / self.cam.f
        unit = r_world * 1.05

        # Sombra projetada no chao 3D (y = 0.02)
        if wy > 0.15:
            sh_center = self.cam.project((wx, 0.02, wz))
            sh_edge = self.cam.project((wx + unit * 2.1, 0.02, wz))
            if sh_center and sh_edge:
                rx = int(_clamp(abs(sh_edge[0] - sh_center[0]), 12, 110))
                ry = max(4, int(rx * 0.28))
                shadow_surf = pg.Surface((rx * 2 + 4, ry * 2 + 4), pg.SRCALPHA)
                alpha = int(_clamp(135 - wy * 10, 35, 130))
                pg.draw.ellipse(shadow_surf, (6, 10, 16, alpha), (2, 2, rx * 2, ry * 2))
                screen.blit(shadow_surf, (int(sh_center[0]) - rx - 2, int(sh_center[1]) - ry - 2))

        # Inclinacao (banking) proporcional a velocidade de strafe + recuo ao levar tiro
        roll = _clamp(-self.bot_vx / 1400.0, -0.26, 0.26)
        pitch = -self.bot_recoil * 0.22 + 0.04 * math.sin(t_now * 4.5)
        yaw = _clamp(self.bot_vx / 2600.0, -0.20, 0.20)
        z_push = self.bot_recoil * 0.65
        flash = _clamp(self.bot_flash / 0.095, 0.0, 1.0)

        # Plumas de propulsao ciano sob as asas (desenhadas atras do chassi)
        flicker = 0.85 + 0.30 * math.sin(t_now * 42.0)
        for side in (-1.0, 1.0):
            p_top = self.cam.project((wx + side * unit * 1.45, wy - unit * 0.72, wz + z_push))
            p_bot = self.cam.project((wx + side * unit * 1.45, wy - unit * (1.85 + 0.65 * flicker), wz + z_push))
            if p_top and p_bot:
                pg.draw.line(screen, LIGHT_CYAN, p_top, p_bot, max(3, int(self.target_radius * 0.28)))
                pg.draw.line(screen, (210, 248, 255), p_top, (
                    _lerp(p_top[0], p_bot[0], 0.55),
                    _lerp(p_top[1], p_bot[1], 0.55),
                ), max(2, int(self.target_radius * 0.14)))

        # Chassi 3D composto como corpo rigido ao redor de (wx, wy, wz + z_push)
        pivot = (wx, wy, wz + z_push)
        faces = []
        # Corpo blindado central
        faces.extend(_box_faces(
            0, 0, 0, unit * 2.35, unit * 2.10, unit * 1.05,
            STEEL_MID, roll=roll, pitch=pitch, yaw=yaw, outline=STEEL_LIGHT,
            pivot=pivot, local_offset=(0.0, 0.0, unit * 0.55),
        ))
        # Placas de ombro/asas esquerda e direita
        for side in (-1.0, 1.0):
            faces.extend(_box_faces(
                0, 0, 0, unit * 0.92, unit * 1.65, unit * 1.25,
                STEEL_DARK, roll=roll, pitch=pitch, yaw=yaw, outline=LANE_LINE,
                pivot=pivot, local_offset=(side * unit * 1.65, unit * 0.05, unit * 0.42),
            ))
            # Aleta de destaque ambar no topo da asa
            faces.extend(_box_faces(
                0, 0, 0, unit * 0.55, unit * 0.22, unit * 0.90,
                LIGHT_AMBER, roll=roll, pitch=pitch, yaw=yaw,
                pivot=pivot, local_offset=(side * unit * 1.65, unit * 0.96, unit * 0.35),
            ))
        # Modulo superior (cabeca/sensor do drone)
        faces.extend(_box_faces(
            0, 0, 0, unit * 1.35, unit * 0.58, unit * 0.92,
            STEEL_DARK, roll=roll, pitch=pitch, yaw=yaw, outline=LIGHT_CYAN,
            pivot=pivot, local_offset=(0.0, unit * 1.38, unit * 0.45),
        ))
        # Base inferior estabilizadora
        faces.extend(_box_faces(
            0, 0, 0, unit * 1.45, unit * 0.42, unit * 0.85,
            STEEL_DARK, roll=roll, pitch=pitch, yaw=yaw, outline=STEEL_MID,
            pivot=pivot, local_offset=(0.0, -unit * 1.22, unit * 0.50),
        ))
        self._draw_faces_sorted(screen, faces, extra_flash=flash)

        # Barra de HP e tag tatica acima do robo
        r = self.target_radius
        bx = int(round(tx))
        by = int(round(ty - r * 2.55))
        if by > 18:
            bw, bh = 58, 6
            pg.draw.rect(screen, (14, 20, 30), (bx - bw // 2 - 1, by - 1, bw + 2, bh + 2))
            frac = _clamp(self.bot_hp / max(1, self.bot_max_hp), 0.0, 1.0)
            hp_col = LIGHT_EMERALD if frac > 0.55 else LIGHT_AMBER if frac > 0.25 else WARN_ORANGE
            pg.draw.rect(screen, hp_col, (bx - bw // 2, by, int(bw * frac), bh))
            dist_lbl = self.font_xs.render(f"BOT {int(round(z_bot))}M", True, HUD_MUTED)
            screen.blit(dist_lbl, (bx - dist_lbl.get_width() // 2, by - 14))

    def _draw_target_core(self, screen, target, locked: bool):
        """Desenha o nucleo magenta exatamente em (target_x, target_y) com sombreamento 3D seguro."""
        pg = self.pg
        tx, ty = int(round(target[0])), int(round(target[1]))
        r = self.target_radius

        # Colar metalico escuro ao redor do nucleo (aumenta contraste na deteccao HSV)
        pg.draw.circle(screen, (22, 28, 38), (tx, ty), r + 4)
        ring_col = LIGHT_EMERALD if locked else LIGHT_CYAN
        pg.draw.circle(screen, ring_col, (tx, ty), r + 4, 2)

        # 4 garras externas de fixacao fora do raio magenta
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            p0 = (tx + dx * (r + 5), ty + dy * (r + 5))
            p1 = (tx + dx * (r + 10), ty + dy * (r + 10))
            pg.draw.line(screen, ring_col, p0, p1, 2)

        # Nucleo magenta esferico 3D: 100% dos pixels dentro do raio r passam no detector!
        pg.draw.circle(screen, CORE_RIM, (tx, ty), r)
        pg.draw.circle(screen, CORE_MAIN, (tx, ty), max(2, r - 2))
        # Brilho especular 3D (ainda dentro de HSV_LO..HSV_HI e mascara fallback)
        hl_r = max(3, int(r * 0.42))
        pg.draw.circle(screen, CORE_SPEC, (tx - int(r * 0.24), ty - int(r * 0.24)), hl_r)

    def _draw_weapon(self, screen, cursor, target, t_now: float):
        """Desenha a carabina tatica 3D em primeira pessoa no canto inferior direito."""
        pg = self.pg
        nx = _clamp((cursor[0] - self.w * 0.5) / (self.w * 0.5), -1.0, 1.0)
        ny = _clamp((cursor[1] - self.h * 0.5) / (self.h * 0.5), -1.0, 1.0)

        # Se o alvo chegar perto do canto inferior direito, abaixa a arma suavemente
        prox = 0.0
        if target[0] > self.w * 0.62 and target[1] > self.h * 0.55:
            prox = _clamp(((target[0] - self.w * 0.62) / (self.w * 0.38)) *
                          ((target[1] - self.h * 0.55) / (self.h * 0.45)), 0.0, 1.0)

        # Camera local do viewmodel (independente do mundo)
        vm_cam = Camera3D(self.w, self.h, fov_deg=56.0)
        vm_cam.set_pose(0.0, 0.0, 0.0, 0.0, 0.0)

        bob_x = math.sin(t_now * 2.4) * 0.012
        bob_y = math.cos(t_now * 4.8) * 0.007
        rec = self.recoil
        # Pivot unico da carabina em 1a pessoa (todas as pecas giram juntas como malha rigida)
        pivot = (
            0.52 + nx * 0.12 + bob_x,
            -0.44 - ny * 0.07 + bob_y - prox * 0.28 + rec * 0.03,
            1.28 - rec * 0.14,
        )
        wyaw = -0.22 + nx * 0.26
        wpitch = 0.04 - ny * 0.20 + rec * 0.16
        wroll = -nx * 0.07

        parts = []
        # Coronha / receiver traseiro
        parts.extend(_box_faces(0, 0, 0, 0.17, 0.18, 0.72, (38, 46, 58), roll=wroll, pitch=wpitch, yaw=wyaw,
                                outline=(82, 100, 120), pivot=pivot, local_offset=(0.0, -0.01, 0.05)))
        # Receiver superior chanfrado / guarda-mao
        parts.extend(_box_faces(0, 0, 0, 0.13, 0.12, 0.68, (58, 70, 86), roll=wroll, pitch=wpitch, yaw=wyaw,
                                outline=(112, 134, 156), pivot=pivot, local_offset=(0.0, 0.04, 0.62)))
        # Trilho energetico ciano lateral (lado esquerdo voltado para a camera)
        parts.extend(_box_faces(0, 0, 0, 0.025, 0.028, 0.56, LIGHT_CYAN, roll=wroll, pitch=wpitch, yaw=wyaw,
                                pivot=pivot, local_offset=(-0.072, 0.045, 0.56)))
        # Cano fino frontal + freio de boca
        parts.extend(_box_faces(0, 0, 0, 0.068, 0.068, 0.26, (32, 38, 48), roll=wroll, pitch=wpitch, yaw=wyaw,
                                outline=LIGHT_AMBER, pivot=pivot, local_offset=(0.0, 0.045, 1.06)))
        # Base baixa da mira reflex + laterais finas (sem bloco gigante)
        parts.extend(_box_faces(0, 0, 0, 0.10, 0.03, 0.20, (32, 40, 50), roll=wroll, pitch=wpitch, yaw=wyaw,
                                outline=(86, 108, 128), pivot=pivot, local_offset=(0.0, 0.105, 0.28)))
        for s_side in (-0.042, 0.042):
            parts.extend(_box_faces(0, 0, 0, 0.016, 0.065, 0.16, (34, 44, 56), roll=wroll, pitch=wpitch, yaw=wyaw,
                                    outline=LIGHT_EMERALD, pivot=pivot, local_offset=(s_side, 0.145, 0.28)))

        # Renderiza partes da arma ordenadas por profundidade
        draw_list = []
        for pts, normal, base_col, outline in parts:
            cx = (pts[0][0] + pts[1][0] + pts[2][0] + pts[3][0]) * 0.25
            cy = (pts[0][1] + pts[1][1] + pts[2][1] + pts[3][1]) * 0.25
            cz = (pts[0][2] + pts[1][2] + pts[2][2] + pts[3][2]) * 0.25
            if _dot(normal, (-cx, -cy, -cz)) <= 0.0:
                continue
            clipped = vm_cam.clip_poly_near(pts)
            if len(clipped) < 3:
                continue
            avg_z = sum(p[2] for p in clipped) / len(clipped)
            ndotl = max(0.0, _dot(normal, (-0.3, 0.85, -0.4)))
            col = _shade_rgb(base_col, 0.58 + 0.52 * ndotl)
            if self.muzzle_flash > 0.0:
                col = _lerp_rgb(col, LIGHT_AMBER, 0.22)
            pts2d = [vm_cam.project_cam(p) for p in clipped]
            draw_list.append((avg_z, pts2d, col, outline))

        draw_list.sort(key=lambda it: it[0], reverse=True)
        for _, pts2d, col, outline in draw_list:
            pg.draw.polygon(screen, col, pts2d)
            if outline:
                pg.draw.polygon(screen, outline, pts2d, 1)

        # Ponta exata do cano transformada pelo mesmo pivot rigido da arma
        mx_l, my_l, mz_l = _rot_xyz(0.0, 0.045, 1.22, roll=wroll, pitch=wpitch, yaw=wyaw)
        muzzle_pt = vm_cam.project_cam((pivot[0] + mx_l, pivot[1] + my_l, pivot[2] + mz_l))
        if muzzle_pt:
            self._muzzle_screen = (int(muzzle_pt[0]), int(muzzle_pt[1]))

        # Flash de disparo na boca do cano (cores quentes ambar/ouro/branco)
        if self.muzzle_flash > 0.0:
            mx, my = self._muzzle_screen
            s = int(20 + 26 * (self.muzzle_flash / 0.055))
            pts = []
            for k in range(10):
                ang = k * math.pi / 5.0 + t_now * 17.0
                rad = s if k % 2 == 0 else s * 0.36
                pts.append((mx + math.cos(ang) * rad, my + math.sin(ang) * rad))
            pg.draw.polygon(screen, (255, 165, 36), pts)
            pg.draw.circle(screen, (255, 245, 200), (mx, my), max(5, s // 3))

    def _draw_fx(self, screen):
        pg = self.pg
        # Tracers
        for tr in self.tracers:
            frac = _clamp(tr.life / tr.max_life, 0.0, 1.0)
            col = _lerp_rgb(LIGHT_CYAN, (255, 232, 130), frac) if tr.hit else _lerp_rgb(STEEL_LIGHT, LIGHT_AMBER, frac)
            pg.draw.line(screen, col, (int(tr.x0), int(tr.y0)), (int(tr.x1), int(tr.y1)), 3 if tr.hit else 2)

        # Faiscas
        for s in self.sparks:
            frac = _clamp(s.life / s.max_life, 0.0, 1.0)
            col = _shade_rgb(s.color, 0.4 + 0.6 * frac)
            pg.draw.circle(screen, col, (int(s.x), int(s.y)), max(1, int(s.size * frac)))

        # Estojos ejetados
        for sh in self.shells:
            dx = math.cos(sh.angle) * 5.0
            dy = math.sin(sh.angle) * 5.0
            pg.draw.line(screen, (232, 188, 68), (int(sh.x - dx), int(sh.y - dy)), (int(sh.x + dx), int(sh.y + dy)), 3)

        # Popups de dano
        for pop in self.popups:
            surf = self.font_sm.render(pop.text, True, pop.color)
            screen.blit(surf, (int(pop.x) - surf.get_width() // 2, int(pop.y)))

    def _draw_reticle(self, screen, cursor, locked: bool):
        """Mira FPS tatica com centro aberto (nao fragmenta o contorno magenta do alvo)."""
        pg = self.pg
        cx, cy = int(round(cursor[0])), int(round(cursor[1]))
        gap = int(9 + self.recoil * 10)
        arm = 10
        col = LIGHT_EMERALD if locked else (218, 245, 255)

        # 4 tracos principais com sombra sutil
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            p0 = (cx + dx * gap, cy + dy * gap)
            p1 = (cx + dx * (gap + arm), cy + dy * (gap + arm))
            pg.draw.line(screen, (10, 16, 24), (p0[0] + 1, p0[1] + 1), (p1[0] + 1, p1[1] + 1), 3)
            pg.draw.line(screen, col, p0, p1, 2)

        # Arco externo sutil quando travado no alvo
        if locked:
            r = gap + arm + 5
            rect = pg.Rect(cx - r, cy - r, r * 2, r * 2)
            for a0 in (0.25, 1.82, 3.39, 4.96):
                pg.draw.arc(screen, LIGHT_EMERALD, rect, a0, a0 + 0.95, 2)

        # Hitmarker diagonal ao acertar
        if self.hitmarker > 0.0:
            hm_in = gap + 2
            hm_out = gap + 11
            hcol = LIGHT_AMBER if self.hitmarker > 0.06 else (245, 250, 255)
            for sx in (-1, 1):
                for sy in (-1, 1):
                    pg.draw.line(screen, hcol, (cx + sx * hm_in, cy + sy * hm_in), (cx + sx * hm_out, cy + sy * hm_out), 2)

    def _draw_hud(self, screen, mode: str, err: float, t: float, locked: bool):
        pg = self.pg
        # Painel superior esquerdo: telemetria do rastreador
        tl = self._hud_tl
        tl.fill((0, 0, 0, 0))
        pg.draw.rect(tl, HUD_BG, (0, 0, tl.get_width(), tl.get_height()), border_radius=6)
        pg.draw.rect(tl, HUD_BORDER, (0, 0, tl.get_width(), tl.get_height()), 1, border_radius=6)
        tl.blit(self.font_md.render(f"[3D]  {MODE_LABELS.get(mode, mode.upper())}", True, LIGHT_EMERALD), (12, 10))
        err_col = LIGHT_EMERALD if locked else (LIGHT_AMBER if err < 80 else WARN_ORANGE)
        tl.blit(self.font_sm.render(f"ERRO: {err:6.1f} px   T: {t:6.1f} s", True, HUD_TEXT), (12, 38))
        status_txt = "TRAVADO NO ALVO" if locked else "RASTREANDO..."
        tl.blit(self.font_sm.render(f"STATUS: {status_txt}", True, err_col), (12, 62))
        screen.blit(tl, (12, 12))

        # Painel superior direito: placar e precisao
        tr = self._hud_tr
        tr.fill((0, 0, 0, 0))
        pg.draw.rect(tr, HUD_BG, (0, 0, tr.get_width(), tr.get_height()), border_radius=6)
        pg.draw.rect(tr, HUD_BORDER, (0, 0, tr.get_width(), tr.get_height()), 1, border_radius=6)
        acc = (100.0 * self.hits / self.shots) if self.shots else 0.0
        lock_pct = (100.0 * self.lock_frames / max(1, self.total_frames))
        tr.blit(self.font_md.render(f"SCORE: {self.score:06d}", True, LIGHT_AMBER), (12, 10))
        tr.blit(self.font_sm.render(f"HITS: {self.hits:<4d}  ACC: {acc:5.1f}%", True, HUD_TEXT), (12, 38))
        af_txt = "ON" if self.autofire else "OFF"
        af_col = LIGHT_EMERALD if self.autofire else HUD_MUTED
        tr.blit(self.font_sm.render(f"LOCK: {lock_pct:4.1f}%   AUTO: {af_txt}", True, af_col), (12, 62))
        screen.blit(tr, (self.w - tr.get_width() - 12, 12))

        # Banner de eliminacao / quebra de escudo no topo central
        if self.kill_banner_t > 0.0 and self.kill_banner:
            surf = self.font_lg.render(self.kill_banner, True, LIGHT_AMBER)
            bx = (self.w - surf.get_width()) // 2
            pg.draw.rect(screen, (14, 22, 34), (bx - 14, 14, surf.get_width() + 28, 32), border_radius=5)
            pg.draw.rect(screen, LIGHT_AMBER, (bx - 14, 14, surf.get_width() + 28, 32), 1, border_radius=5)
            screen.blit(surf, (bx, 19))

        # Mini-radar tatico no canto inferior esquerdo
        rad = self._radar_surf
        rad.fill((0, 0, 0, 0))
        rw, rh = rad.get_width(), rad.get_height()
        pg.draw.rect(rad, HUD_BG, (0, 0, rw, rh), border_radius=6)
        pg.draw.rect(rad, HUD_BORDER, (0, 0, rw, rh), 1, border_radius=6)
        rad.blit(self.font_xs.render("RADAR", True, HUD_MUTED), (8, 5))
        ox, oy = rw // 2, rh - 14
        # Cone de visao do jogador
        pg.draw.line(rad, (38, 86, 110), (ox, oy), (ox - 46, 22), 1)
        pg.draw.line(rad, (38, 86, 110), (ox, oy), (ox + 46, 22), 1)
        pg.draw.circle(rad, (32, 72, 94), (ox, oy), 34, 1)
        pg.draw.circle(rad, (32, 72, 94), (ox, oy), 68, 1)
        pg.draw.polygon(rad, LIGHT_CYAN, [(ox, oy - 5), (ox - 4, oy + 4), (ox + 4, oy + 4)])
        # Posicao do robo no radar (cor ambar/laranja, NUNCA magenta!)
        if hasattr(self, "_bot_world"):
            bx_w, _, bz_w = self._bot_world
            rx = int(_clamp(ox + bx_w * 3.0, 10, rw - 10))
            ry = int(_clamp(oy - bz_w * 2.2, 22, oy - 6))
            pg.draw.circle(rad, WARN_ORANGE, (rx, ry), 4)
            pg.draw.circle(rad, LIGHT_AMBER, (rx, ry), 6, 1)
        screen.blit(rad, (12, self.h - rh - 34))

        # Barra de controles no rodape
        hint = "[1-4] Trajetorias   [5] Shooter 3D   [Click/Espaco] Atirar   [F] Auto-Fire   [V] 3D/2D   [ESC] Sair"
        h_surf = self.font_xs.render(hint, True, HUD_MUTED)
        hx = (self.w - h_surf.get_width()) // 2
        hy = self.h - 24
        pg.draw.rect(screen, (10, 16, 26), (hx - 10, hy - 3, h_surf.get_width() + 20, 20), border_radius=4)
        screen.blit(h_surf, (hx, hy))

    def render(self, screen, target, cursor, mode: str, t: float):
        """Renderiza o quadro completo respeitando a prioridade de visibilidade do alvo."""
        err = math.hypot(target[0] - cursor[0], target[1] - cursor[1])
        locked = err <= self.target_radius + 4.0

        self._draw_arena(screen)
        self._draw_bot_body(screen, target, t)
        self._draw_weapon(screen, cursor, target, t)
        self._draw_fx(screen)
        self._draw_hud(screen, mode, err, t, locked)
        # Nucleo magenta desenhado por cima de cenario, arma, efeitos e HUD:
        # visibilidade 100% garantida para o detector HSV em qualquer posicao da janela.
        self._draw_target_core(screen, target, locked)
        self._draw_reticle(screen, cursor, locked)
