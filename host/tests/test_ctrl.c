/* Testes do modulo de controle compilado nativamente (spec, secao 9).
 * Planta: integrador (1 px por contagem) + atraso. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "sil_shim.h"
#include "../../firmware/src/ctrl/pid.h"
#include "../../firmware/src/ctrl/estimator.h"
#include "../../firmware/src/proto/proto.h"
#include "../../firmware/src/proto/crc8.h"

static int failures, checks;
#define CHECK(cond, ...) do { checks++; if (!(cond)) { failures++; \
    printf("FALHOU %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* ---------- PID isolado ---------- */
static void test_pid_saturation(void)
{
    pid_cfg_t cfg = { Q16_CONST(1.0), 0, 0, 0, 3 };
    pid_state_t s; pid_reset(&s);
    CHECK(pid_step(&s, &cfg, 2000) == 127, "saturacao positiva");
    CHECK(pid_step(&s, &cfg, -2000) == -127, "saturacao negativa");
    CHECK(pid_step(&s, &cfg, 32767) == 127, "erro acima de PID_E_MAX e limitado");
    cfg.kp = PID_GAIN_MAX; cfg.ki = PID_GAIN_MAX; cfg.kd = PID_GAIN_MAX;
    pid_reset(&s);
    for (int i = 0; i < 2000; i++) {
        int8_t u = pid_step(&s, &cfg, (i & 1) ? PID_E_MAX : -PID_E_MAX);
        CHECK(u >= -127, "u fora da faixa com ganhos maximos");
    }
}

static void test_pid_antiwindup(void)
{
    pid_cfg_t cfg = { Q16_CONST(0.5), Q16_CONST(0.05), 0, 0, 3 };
    pid_state_t s; pid_reset(&s);
    for (int i = 0; i < 5000; i++)
        pid_step(&s, &cfg, 1000);                   /* saturado por 5 s */
    CHECK(s.integ == 0, "integrador cresceu saturado: %ld", (long)s.integ);
    /* sem anti-windup o integrador estaria em +127 e a saida demoraria a inverter */
    CHECK(pid_step(&s, &cfg, -10) < 0, "saida deveria inverter logo apos a saturacao");

    cfg.kp = 0; cfg.ki = Q16_CONST(1.0);            /* so I: limita em +-127 */
    pid_reset(&s);
    for (int i = 0; i < 1000; i++) pid_step(&s, &cfg, 100);
    CHECK(s.integ <= Q16_FROM_INT(127), "integrador passou do limite");
}

static void test_pid_residual(void)
{
    /* Kp*e = 0.3 contagem/passo: em 1000 passos tem que sair 300 (+-1) */
    pid_cfg_t cfg = { Q16_CONST(0.1), 0, 0, 0, 3 };
    pid_state_t s; pid_reset(&s);
    long sum = 0;
    for (int i = 0; i < 1000; i++) sum += pid_step(&s, &cfg, 3);
    CHECK(labs(sum - 300) <= 1, "residuo +: soma = %ld", sum);
    pid_reset(&s); sum = 0;
    for (int i = 0; i < 1000; i++) sum += pid_step(&s, &cfg, -3);
    CHECK(labs(sum + 300) <= 1, "residuo -: soma = %ld", sum);
}

static void test_pid_deadband(void)
{
    pid_cfg_t cfg = { Q16_CONST(0.3), Q16_CONST(0.01), 0, 2, 3 };
    pid_state_t s; pid_reset(&s);
    for (int i = 0; i < 100; i++) pid_step(&s, &cfg, 50);
    q16_t integ = s.integ;
    for (int i = 0; i < 100; i++)
        CHECK(pid_step(&s, &cfg, (i & 1) ? 2 : -2) == 0, "mexeu dentro da zona morta");
    CHECK(s.integ == integ, "integrador mudou na zona morta");
    CHECK(s.resid == 0, "residuo nao foi zerado");
}

static void test_pid_derivative(void)
{
    pid_cfg_t cfg = { 0, 0, Q16_CONST(8.0), 0, 0 };     /* sem filtro */
    pid_state_t s; pid_reset(&s);
    CHECK(pid_step(&s, &cfg, 100) == 0, "kick da derivada no primeiro passo");
    CHECK(pid_step(&s, &cfg, 102) == 16, "D = kd * delta");
    CHECK(pid_step(&s, &cfg, 102) == 0, "D com erro constante");
}

/* ---------- estimador isolado ---------- */
static void test_estimator(void)
{
    est_t e; est_reset(&e); e.gain_q8 = 256; e.enabled = true;
    est_measure(&e, 100, 0);
    est_apply(&e, 10); est_apply(&e, 5);
    CHECK(est_get(&e) == 85, "desconto dos comandos: %d", est_get(&e));
    est_measure(&e, 90, 1);     /* a medicao viu o 10, falta o 5 */
    CHECK(est_get(&e) == 85, "latencia L=1: %d", est_get(&e));
    est_measure(&e, 100, 200);  /* L limitado ao historico */
    CHECK(est_get(&e) == 85, "L > historico: %d", est_get(&e));
    e.enabled = false;
    est_measure(&e, 100, 2);
    est_apply(&e, 50);
    CHECK(est_get(&e) == 100, "desligado = ZOH: %d", est_get(&e));
    e.enabled = true; e.gain_q8 = 384;                   /* 1,5 px/contagem */
    est_measure(&e, 100, 0); est_apply(&e, 10);
    CHECK(est_get(&e) == 85, "ganho da planta: %d", est_get(&e));
}

/* ---------- firmware completo (aplicacao + passo de controle) ---------- */
static uint8_t rx[16384];

static void send(uint8_t type, const uint8_t *payload, uint8_t len, int bad_crc)
{
    uint8_t f[16] = { PROTO_SYNC0, PROTO_SYNC1, type, len };
    if (len) memcpy(&f[4], payload, len);
    f[4 + len] = (uint8_t)(crc8(&f[2], (uint8_t)(len + 2)) ^ (bad_crc ? 0x55 : 0));
    for (int i = 0; i < len + 5; i++) sil_feed(f[i]);
}

static void send_meas(uint8_t seq, uint8_t flags, int ex, int ey, int bad_crc)
{
    uint8_t p[6] = { seq, flags, (uint8_t)ex, (uint8_t)(ex >> 8), (uint8_t)ey, (uint8_t)(ey >> 8) };
    send(PROTO_T_MEAS, p, 6, bad_crc);
}

static void set_param(int id, long v)
{
    uint8_t p[5] = { (uint8_t)id, (uint8_t)v, (uint8_t)(v >> 8), (uint8_t)(v >> 16), (uint8_t)(v >> 24) };
    send(PROTO_T_SET_PARAM, p, 5, 0);
}

static void set_mode(int mode)
{
    uint8_t m = (uint8_t)mode;
    send(PROTO_T_SET_MODE, &m, 1, 0);
}

static void drain(void) { while (sil_read(rx, sizeof rx) > 0) { } }

/* Le tudo o que o firmware enviou e copia o ultimo quadro do tipo pedido. */
static int last_frame(uint8_t type, uint8_t *out)
{
    int n = sil_read(rx, sizeof rx), found = 0;
    for (int i = 0; i + 5 <= n; i += rx[i + 3] + 5)
        if (rx[i + 2] == type) {
            memcpy(out, &rx[i], (size_t)rx[i + 3] + 5);
            found = 1;
        }
    return found;
}

/* Codigo do ultimo ACK (-1 se nao houve). */
static int last_ack(uint8_t src)
{
    uint8_t f[64];
    if (!last_frame(PROTO_T_ACK, f) || f[4] != src) return -1;
    return f[5];
}

/* offsets no quadro TELEM */
enum { T_STATE = 10, T_FLAGS = 11, T_EHX = 16, T_ERRS = 24, T_DROP = 26 };

/* ---------- planta: integrador (1 px por contagem) + atraso ---------- */
#define QLEN 256
typedef struct {
    int dc, dh;                 /* atrasos captura->MCU e MCU->cursor, em passos de 1 ms */
    long cx, cy, tx, ty;
    int8_t hx[QLEN], hy[QLEN];  /* comandos em transito */
    long mex[QLEN], mey[QLEN];  /* medicoes em transito */
    int mdue[QLEN], mhead, mtail;
    int k;
    uint8_t seq;
    double cap_acc;
    int flags;
    int corrupt;                /* 1: CRC errado; 2: SEQ repetido */
} plant_t;

static void plant_init(plant_t *p, int dc, int dh)
{
    memset(p, 0, sizeof *p);
    p->dc = dc; p->dh = dh; p->flags = 1;
    sil_persist_clear();
    sil_init();
    set_param(PARAM_LATENCY, dc + dh);
}

/* Um passo de 1 ms. link=0 simula o PC parado. Retorna u_x. */
static int plant_step(plant_t *p, int link)
{
    int8_t ux, uy;
    p->cap_acc += 60.0 / 1000.0;                /* captura a 60 Hz */
    if (p->cap_acc >= 1.0) {
        p->cap_acc -= 1.0;
        p->mex[p->mhead] = p->tx - p->cx;
        p->mey[p->mhead] = p->ty - p->cy;
        p->mdue[p->mhead] = p->k + p->dc;
        p->mhead = (p->mhead + 1) % QLEN;
    }
    while (p->mtail != p->mhead && p->mdue[p->mtail] <= p->k) {     /* medicoes que chegam agora */
        if (link) {
            uint8_t seq = p->corrupt == 2 ? p->seq : ++p->seq;
            send_meas(seq, (uint8_t)p->flags, (int)p->mex[p->mtail], (int)p->mey[p->mtail], p->corrupt == 1);
        }
        p->mtail = (p->mtail + 1) % QLEN;
    }
    sil_step(&ux, &uy);
    p->hx[p->k % QLEN] = ux;
    p->hy[p->k % QLEN] = uy;
    if (p->k >= p->dh) {                        /* o comando de dh passos atras chega ao cursor */
        p->cx += p->hx[(p->k - p->dh) % QLEN];
        p->cy += p->hy[(p->k - p->dh) % QLEN];
    }
    p->k++;
    return ux;
}

static void set_gains(double kp, double ki_s, double kd_s)
{
    set_param(PARAM_KP, (long)(kp * 65536 + 0.5));
    set_param(PARAM_KI, (long)(ki_s / CTRL_HZ * 65536 + 0.5));
    set_param(PARAM_KD, (long)(kd_s * CTRL_HZ * 65536 + 0.5));
}

static void start_auto(void)
{
    set_mode(CTRL_AUTO);
    sil_button(0);                              /* BOOTSEL: habilita */
}

typedef struct { double overshoot_pct, settle_ms, ss_err; } step_metrics_t;

static step_metrics_t run_step(int dc, int dh, double kp, int est_on, int amp)
{
    plant_t p; plant_init(&p, dc, dh);
    set_gains(kp, 0, 0);
    set_param(PARAM_EST_EN, est_on);
    start_auto();
    for (int i = 0; i < 200; i++) plant_step(&p, 1);
    p.tx = amp;
    int k0 = p.k, last_out = k0;
    long peak = 0;
    for (int i = 0; i < 3000; i++) {
        plant_step(&p, 1);
        if (p.cx > peak) peak = p.cx;
        if (labs(p.cx - amp) > amp / 50) last_out = p.k;
        if (i % 500 == 0) drain();
    }
    step_metrics_t m;
    m.overshoot_pct = peak > amp ? 100.0 * (double)(peak - amp) / amp : 0.0;
    m.settle_ms = (last_out - k0 + 1) * 1.0;
    m.ss_err = (double)labs(p.cx - amp);
    return m;
}

static void test_closed_loop_step(void)
{
    /* atraso total 30 ms: 20 de captura->MCU + 10 de HID */
    step_metrics_t m = run_step(20, 10, 0.06, 1, 500);
    printf("  degrau 500 px, com estimador, Kp=0.06: overshoot %.1f%%, acomodacao %.0f ms, erro %.0f px\n",
           m.overshoot_pct, m.settle_ms, m.ss_err);
    CHECK(m.overshoot_pct < 10.0, "overshoot %.1f%%", m.overshoot_pct);
    CHECK(m.settle_ms < 250.0, "acomodacao %.0f ms", m.settle_ms);
    CHECK(m.ss_err <= 2.0, "erro em regime %.0f px", m.ss_err);

    step_metrics_t z = run_step(20, 10, 0.06, 0, 500);
    printf("  mesmo caso SEM estimador:              overshoot %.1f%%, acomodacao %.0f ms, erro %.0f px\n",
           z.overshoot_pct, z.settle_ms, z.ss_err);
    CHECK(z.overshoot_pct > m.overshoot_pct, "o estimador deveria reduzir o overshoot");
}

static void test_estimator_exact(void)
{
    /* Com L correto, alvo parado e ganho 1, e^ tem que ser exatamente o erro
     * "futuro" (alvo - cursor - comandos em transito) logo apos cada passo. */
    plant_t p; plant_init(&p, 20, 10);
    set_gains(0.1, 0, 0);
    start_auto();
    p.tx = 400; p.ty = -250;
    int bad = 0, seen = 0;
    uint8_t f[64];
    for (int i = 0; i < 1200; i++) {
        plant_step(&p, 1);
        long transit = 0;
        for (int j = 1; j <= p.dh; j++)
            if (p.k - j >= 0) transit += p.hx[(p.k - j) % QLEN];
        if (last_frame(PROTO_T_TELEM, f) && i > 80) {
            seen++;
            if (proto_get_i16(&f[T_EHX]) != p.tx - p.cx - transit) bad++;
        }
    }
    CHECK(seen > 100 && bad == 0, "e^ divergiu do erro real em %d de %d amostras", bad, seen);
    CHECK(labs(p.cx - 400) <= 1 && labs(p.cy + 250) <= 1, "nao chegou ao alvo: %ld %ld", p.cx, p.cy);
}

static void test_ramp_integral(void)
{
    /* Rampa de 300 px/s. So P: erro = v/Kp + v*atraso. Com I o termo v/Kp
     * some, mas sobra v*atraso (~9 px): o estimador compensa os comandos em
     * transito, nao o movimento do alvo durante a latencia. */
    double err[2];
    for (int t = 0; t < 2; t++) {
        plant_t p; plant_init(&p, 20, 10);
        set_gains(0.04, t ? 4.0 : 0.0, 0);
        set_param(PARAM_DEADBAND, 0);
        start_auto();
        double tx = 0, acc = 0;
        for (int i = 0; i < 6000; i++) {
            tx += 300.0 / 1000.0; p.tx = (long)tx;
            plant_step(&p, 1);
            if (i >= 5000) acc += (double)(p.tx - p.cx);
            if (i % 500 == 0) drain();
        }
        err[t] = acc / 1000.0;
    }
    printf("  rampa 300 px/s: erro medio so P = %.1f px, com I = %.1f px\n", err[0], err[1]);
    CHECK(err[0] > 5.0, "so P deveria ter erro de rastreamento");
    CHECK(err[1] < err[0] - 5.0, "o integrador deveria tirar o termo v/Kp do erro");
    CHECK(err[1] < 0.3 * 40.0, "sobrou mais que v * atraso");
}

static void test_failsafe(void)
{
    uint8_t f[64];
    plant_t p; plant_init(&p, 20, 10);
    set_gains(0.0025, 0, 0);
    start_auto();
    p.tx = 2000;
    for (int i = 0; i < 200; i++) plant_step(&p, 1);
    CHECK(plant_step(&p, 1) != 0, "deveria estar movendo");
    int stop = -1;
    for (int i = 0; i < 200; i++)
        if (plant_step(&p, 0) == 0 && stop < 0) stop = i;
    printf("  failsafe: saida zerada %d ms apos o ultimo pacote\n", stop + 1);
    CHECK(stop >= 0 && stop + 1 <= 100, "reacao do failsafe > 100 ms");
    drain();
    for (int i = 0; i < 10; i++) plant_step(&p, 0);
    CHECK(last_frame(PROTO_T_TELEM, f) && !(f[T_FLAGS] & CTRL_FL_LINK_OK), "telemetria deveria indicar link perdido");
    for (int i = 0; i < 60; i++) plant_step(&p, 1);
    CHECK(plant_step(&p, 1) != 0, "deveria retomar quando o link volta");

    /* alvo invalido: u = 0 */
    p.flags = 0;
    for (int i = 0; i < 60; i++) plant_step(&p, 1);
    CHECK(plant_step(&p, 1) == 0, "alvo invalido deveria zerar u");
    p.flags = 1;
    for (int i = 0; i < 60; i++) plant_step(&p, 1);

    /* SEQ repetido e CRC invalido: descartados e contados */
    p.corrupt = 2;
    for (int i = 0; i < 50; i++) plant_step(&p, 1);
    p.corrupt = 0;
    for (int i = 0; i < 50; i++) plant_step(&p, 1);
    p.corrupt = 1;
    for (int i = 0; i < 50; i++) plant_step(&p, 1);
    p.corrupt = 0;
    drain();
    for (int i = 0; i < 50; i++) plant_step(&p, 1);
    CHECK(last_frame(PROTO_T_TELEM, f) && proto_get_i16(&f[T_ERRS]) >= 4, "contador de erros = %d", proto_get_i16(&f[T_ERRS]));
    CHECK(f[T_FLAGS] & CTRL_FL_LINK_OK, "link deveria ter voltado");

    /* desabilitado pelo BOOTSEL: nada sai */
    int8_t ux, uy; int moved = 0;
    sil_button(0);
    for (int i = 0; i < 50; i++) { send_meas(++p.seq, 1, 500, 500, 0); moved |= sil_step(&ux, &uy); }
    CHECK(!moved, "saiu movimento com a saida desabilitada");
    sil_button(0);
    moved = 0;
    for (int i = 0; i < 50; i++) { send_meas(++p.seq, 1, 500, 500, 0); moved |= sil_step(&ux, &uy); }
    CHECK(moved, "deveria mover depois de habilitar de novo");

    /* fila u cheia: comando descartado e contado, sem travar */
    sil_set_hid_full(1);
    for (int i = 0; i < 20; i++) { send_meas(++p.seq, 1, 500, 500, 0); sil_step(&ux, &uy); }
    sil_set_hid_full(0);
    drain();
    for (int i = 0; i < 5; i++) { send_meas(++p.seq, 1, 500, 500, 0); sil_step(&ux, &uy); }
    CHECK(last_frame(PROTO_T_TELEM, f) && f[T_DROP] > 0, "hid_drop nao contou");

    /* pressao longa no BOOTSEL: DESLIGADO na hora, e continua desabilitado */
    sil_button(1);
    moved = 0;
    for (int i = 0; i < 50; i++) { send_meas(++p.seq, 1, 500, 500, 0); moved |= sil_step(&ux, &uy); }
    CHECK(!moved, "emergencia nao parou a saida");
    CHECK(last_frame(PROTO_T_TELEM, f) && f[T_STATE] == CTRL_OFF && !(f[T_FLAGS] & CTRL_FL_ENABLED),
          "emergencia deveria deixar DESLIGADO e desabilitado");

    /* USB suspenso: DESLIGADO */
    start_auto();
    moved = 0;
    for (int i = 0; i < 20; i++) { send_meas(++p.seq, 1, 500, 500, 0); moved |= sil_step(&ux, &uy); }
    CHECK(moved, "deveria mover em AUTOMATICO habilitado");
    sil_set_usb(0);
    moved = 0;
    for (int i = 0; i < 20; i++) { send_meas(++p.seq, 1, 500, 500, 0); moved |= sil_step(&ux, &uy); }
    CHECK(!moved, "USB suspenso deveria parar a saida");
    CHECK(last_frame(PROTO_T_TELEM, f) && f[T_STATE] == CTRL_OFF, "USB suspenso deveria levar a DESLIGADO");
}

static void test_ident(void)
{
    uint8_t f[64];
    plant_t p; plant_init(&p, 20, 10);
    set_param(PARAM_ID_AMP, 2);
    set_mode(CTRL_IDENT);
    int8_t ux, uy; long sum = 0; int nonzero = 0, maxabs = 0;
    for (int i = 0; i < 50; i++) { sil_step(&ux, &uy); nonzero |= ux; }
    CHECK(!nonzero, "identificacao comecou antes de habilitar");
    sil_button(0);
    for (int n = 0; n < 6000; n++) {
        sil_step(&ux, &uy);
        sum += ux;
        if (abs(ux) > maxabs) maxabs = abs(ux);
        if (ux) nonzero = n;
        if (n % 500 == 0) drain();
    }
    CHECK(maxabs == 2, "amplitude = %d", maxabs);
    CHECK(labs(sum) <= 40, "deriva da identificacao = %ld contagens", sum);
    CHECK(nonzero > 3000 && nonzero < 3800, "duracao = %d passos", nonzero);
    CHECK(last_frame(PROTO_T_TELEM, f) && f[T_STATE] == CTRL_OFF, "deveria voltar a DESLIGADO");
    /* uma configuracao nova nao pode reiniciar a identificacao */
    set_param(PARAM_DEADBAND, 2);
    nonzero = 0;
    for (int i = 0; i < 500; i++) { sil_step(&ux, &uy); nonzero |= ux; }
    CHECK(!nonzero, "identificacao reiniciou sozinha");
}

static void test_protocol(void)
{
    uint8_t f[64];
    int8_t ux, uy;
    sil_persist_clear();
    sil_init();
    drain();

    /* faixas dos parametros */
    set_param(PARAM_KP, 20L * 65536);
    CHECK(last_ack(PROTO_T_SET_PARAM) == PROTO_ERR_RANGE, "Kp fora da faixa deveria dar NACK");
    set_param(PARAM_LATENCY, 128);
    CHECK(last_ack(PROTO_T_SET_PARAM) == PROTO_ERR_RANGE, "L fora da faixa deveria dar NACK");
    set_param(PARAM_KP, -1);
    CHECK(last_ack(PROTO_T_SET_PARAM) == PROTO_ERR_RANGE, "Kp negativo deveria dar NACK");
    set_param(99, 0);
    CHECK(last_ack(PROTO_T_SET_PARAM) == PROTO_ERR_PARAM_ID, "id invalido deveria dar NACK");
    set_param(PARAM_LATENCY, 42);
    CHECK(last_ack(PROTO_T_SET_PARAM) == PROTO_ERR_OK, "L valido deveria dar ACK");
    set_mode(7);
    CHECK(last_ack(PROTO_T_SET_MODE) == PROTO_ERR_MODE, "modo invalido deveria dar NACK");
    send(0x55, NULL, 0, 0);
    CHECK(last_ack(0x55) == PROTO_ERR_TYPE, "tipo desconhecido deveria dar NACK");
    send(PROTO_T_SET_MODE, (const uint8_t *)"\0\0", 2, 0);
    CHECK(last_ack(PROTO_T_SET_MODE) == PROTO_ERR_LEN, "LEN errado deveria dar NACK");

    /* GET_PARAMS: os invalidos nao podem ter alterado nada */
    send(PROTO_T_GET_PARAMS, NULL, 0, 0);
    CHECK(last_frame(PROTO_T_PARAMS, f) && f[3] == PROTO_LEN_PARAMS, "sem resposta ao GET_PARAMS");
    CHECK(proto_get_i32(&f[4 + 4 * (PARAM_LATENCY - 1)]) == 42, "L lido = %ld", (long)proto_get_i32(&f[4 + 4 * (PARAM_LATENCY - 1)]));
    CHECK(proto_get_i32(&f[4 + 4 * (PARAM_KP - 1)]) == Q16_CONST(0.06), "Kp padrao foi alterado");

    /* SAVE so em DESLIGADO; LOAD recupera; o boot carrega a copia salva */
    send(PROTO_T_LOAD, NULL, 0, 0);
    CHECK(last_ack(PROTO_T_LOAD) == PROTO_ERR_STORAGE, "LOAD sem copia salva deveria dar NACK");
    set_mode(CTRL_AUTO);
    for (int i = 0; i < 10; i++) sil_step(&ux, &uy);
    send(PROTO_T_SAVE, NULL, 0, 0);
    CHECK(last_ack(PROTO_T_SAVE) == PROTO_ERR_STATE, "SAVE fora de DESLIGADO deveria dar NACK");
    set_mode(CTRL_OFF);
    for (int i = 0; i < 10; i++) sil_step(&ux, &uy);
    send(PROTO_T_SAVE, NULL, 0, 0);
    CHECK(last_ack(PROTO_T_SAVE) == PROTO_ERR_OK, "SAVE em DESLIGADO deveria dar ACK");
    set_param(PARAM_LATENCY, 7);
    send(PROTO_T_LOAD, NULL, 0, 0);
    CHECK(last_ack(PROTO_T_LOAD) == PROTO_ERR_OK, "LOAD deveria dar ACK");
    sil_init();                                 /* "reset" */
    send(PROTO_T_GET_PARAMS, NULL, 0, 0);
    CHECK(last_frame(PROTO_T_PARAMS, f) && proto_get_i32(&f[4 + 4 * (PARAM_LATENCY - 1)]) == 42, "o boot nao carregou a flash");

    /* o boot sempre comeca desabilitado e em DESLIGADO */
    for (int i = 0; i < 10; i++) sil_step(&ux, &uy);
    CHECK(last_frame(PROTO_T_TELEM, f) && f[T_STATE] == CTRL_OFF && !(f[T_FLAGS] & CTRL_FL_ENABLED), "estado inicial");
    sil_persist_clear();
}

int main(void)
{
    printf("PID\n");
    test_pid_saturation(); test_pid_antiwindup(); test_pid_residual();
    test_pid_deadband(); test_pid_derivative();
    printf("Estimador\n");
    test_estimator();
    printf("Malha fechada (planta: integrador + atraso)\n");
    test_closed_loop_step(); test_estimator_exact(); test_ramp_integral();
    printf("Failsafe / identificacao / protocolo\n");
    test_failsafe(); test_ident(); test_protocol();
    printf("%d verificacoes, %d falhas\n", checks, failures);
    return failures ? 1 : 0;
}
