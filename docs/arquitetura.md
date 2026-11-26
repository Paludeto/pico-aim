# Arquitetura e Resultados Experimentais

*[English version](en/architecture.md)*

Este documento resume as decisões de arquitetura do firmware no RP2040, a comunicação USB, o projeto do controlador digital em ponto fixo e os dados medidos em bancada.

## 1. Divisão entre os núcleos do RP2040

Os módulos de controle (`ctrl/`), protocolo (`proto/`) e máquina de estados (`app/app.c`) são escritos em C11 puro, sem chamadas ao Pico SDK, o que permite testá-los também no PC. O acesso ao hardware fica concentrado em `main.c`, `usb/`, `core1/`, `ui/` e `app/persist.c`.

```text
CORE 0 (main.c)                                   CORE 1 (core1/core1.c)
 tud_task()                                        IRQ do alarme de hardware (1 kHz):
 CDC RX -> parser -> app_on_frame                    fila cmd  -> parâmetros, modo, habilitação
   MEAS ----------------- fila meas (4) ---------->  fila meas -> estimador de latência
   config --------------- fila cmd  (2) ---------->  PID / identificação / failsafe
 pend_x, pend_y <-------- fila u (16) -------------  u (apenas quando != 0)
   -> tud_hid_mouse_report() quando pronto
 TELEM via CDC <--------- fila telem (8) ----------  telemetria decimada (200 Hz)
 BOOTSEL, LED, máquina de estados, watchdog         laço principal: __wfi()
```

- **Core 0:** é o único que acessa o TinyUSB (que não é thread-safe entre núcleos), gerencia parâmetros/modo/habilitação, trata o botão `BOOTSEL` e o LED e acumula movimentos pendentes (até ±32767 contagens por eixo) caso o host atrase o polling HID.
- **Core 1:** executa somente `ctrl_loop_step()` dentro da interrupção de alarme de 1 kHz, rearmada por tempo absoluto (`delayed_by_us`) para evitar deriva acumulada.
- **Filas sem bloqueio:** a comunicação inter-núcleo usa `queue_t` sempre com `try_add`/`try_remove`. Se a fila `u` lotar, o passo é descartado e contado em `hid_drop`.
- **Execução em RAM (`copy_to_ram`):** todo o binário é copiado para a SRAM no boot. Isso permite ler o `BOOTSEL` (que libera momentaneamente o CS da flash QSPI) sem interferir na IRQ de 1 kHz do core 1. Na gravação de parâmetros na flash (`SAVE`), permitida apenas em `DESLIGADO`, o core 1 é pausado com `multicore_lockout`.
- **Supervisão:** um watchdog de 1 s só é realimentado pelo core 0 quando o contador de passos do core 1 avança. Travando qualquer núcleo, a placa reinicia desabilitada. Os pinos `GP2` (duração do passo de controle) e `GP3` (envio de relatório HID) servem para inspeção em osciloscópio.

## 2. USB composto e protocolo CDC

O RP2040 enumera como dispositivo composto *Miscellaneous / IAD* (`VID:PID 1209:0001`), combinando:

- **CDC-ACM (interfaces 0 e 1):** link serial virtual para medições, comandos e telemetria (endpoints `0x81`, `0x02` e `0x82`).
- **HID Mouse (interface 2):** mouse relativo padrão (`TUD_HID_REPORT_DESC_MOUSE()`, endpoint `0x83`, `bInterval = 1 ms`).

Os quadros CDC são little-endian e protegidos por CRC-8 (polinômio `0x07`):

```text
0xA5 0x5A | TIPO (1 B) | LEN (1 B) | PAYLOAD (LEN B) | CRC8(TIPO .. PAYLOAD)
```

| Código | Quadro | Direção | Conteúdo |
|---|---|---|---|
| `0x01` | `MEAS` | PC → MCU | `SEQ` (u8), `FLAGS` (u8, bit 0 = alvo válido), `EX` (i16), `EY` (i16) |
| `0x02` | `SET_PARAM` | PC → MCU | `ID` (u8), `VALOR` (i32) |
| `0x03` | `SET_MODE` | PC → MCU | `MODO` (u8: `0` DESLIGADO, `1` AUTOMÁTICO, `2` IDENTIFICAÇÃO) |
| `0x04`–`0x06` | `SAVE` / `LOAD` / `GET_PARAMS` | PC → MCU | Sem payload |
| `0x80` | `TELEM` (200 Hz) | MCU → PC | `t_us`, `tick`, estado, flags, `em`, `eh`, `Σu`, `errs`, `hid_drop`, `meas_age`, cargas 0/1 |
| `0x81` | `ACK` / `NACK` | MCU → PC | Tipo de origem (u8) e código de erro (u8; `0` = ok) |
| `0x82` | `PARAMS` | MCU → PC | Vetor com os 9 parâmetros em `i32` |

| ID | Parâmetro | Formato | Faixa | Padrão |
|---|---|---|---|---|
| 1 | $K_p$ | Q16.16 contagens/px | $0 \le K_p < 16$ | 0,06 |
| 2 | $K_i \cdot T$ | Q16.16 por amostra | $0 \le K_i T < 16$ | 0 |
| 3 | $K_d / T$ | Q16.16 por amostra | $0 \le K_d / T < 16$ | 0 |
| 4 | Latência $L$ | Passos de 1 ms | 0 a 127 | 30 |
| 5 | Zona morta | px | 0 a 100 | 1 |
| 6 | Filtro derivativo | $n$ ($\alpha = 2^{-n}$) | 0 a 8 | 3 |
| 7 | Amplitude de identificação | Contagens | 1 a 20 | 1 |
| 8 | Ganho da planta $g$ | Q16.16 px/contagem | 0,125 a 8,0 | 1,0 |
| 9 | Estimador | 0 ou 1 | 0 ou 1 | 1 |

**Segurança e estados:** modo (CDC) e habilitação (`BOOTSEL`) são independentes; a placa só move o cursor quando ambos estão ativos. Sem `MEAS` válido por 100 ms, o failsafe zera a saída e o integrador e coloca o LED em padrão de falha (5 Hz). Alvo inválido congela o integrador com saída nula. Pressão longa no `BOOTSEL` ($\ge 1\ \text{s}$) ou suspensão/desconexão USB desligam tudo imediatamente.

## 3. Controlador em ponto fixo e estimador de latência

O caminho HID → cursor no Windows comporta-se como um integrador com ganho $g$ (px/contagem) e atraso de transporte $L$. Como a visão roda a ~60 Hz e o controle a 1 kHz, realimentar diretamente o erro medido $e_m$ faz o controlador integrar o mesmo erro durante ~17 passos seguidos, causando sobressinal ou instabilidade.

Para contornar esse atraso multitaxa, cada eixo mantém um histórico circular de 128 comandos emitidos (estrutura análoga a um preditor de Smith para planta integradora):

1. Ao chegar uma nova medição $e_m$, descontam-se os últimos $L$ comandos já enviados:
   $$\hat{e}[k] = e_m - g \sum_{i=1}^{L} u[k - i]$$
2. A cada passo seguinte de 1 ms, todo comando emitido é abatido na hora de $\hat{e}$:
   $$\hat{e}[k+1] = \hat{e}[k] - g \cdot u[k]$$

Sobre $\hat{e}$ (limitado a $\pm 2047$ px), o PID discreto opera integralmente em inteiros Q16.16 (sem `float` em tempo de execução), com filtro passa-baixas exponencial na derivada, saturação em $\pm 127$ contagens, anti-windup por *clamping*, acumulador de resíduo fracionário e zona morta.

## 4. Medições experimentais

Ensaios conduzidos com Raspberry Pi Pico, Windows 11, captura `mss 9.0.1` a 60 Hz sobre a interface Shooter 3D, aceleração do ponteiro desativada e sensibilidade em 6/11 (CSVs em [`docs/medicoes/`](medicoes/)).

**Identificação em malha aberta (`ident_telem.csv`, degraus $+A/-A$ + PRBS7):**
- Eixo X: $g = 1{,}250\ \text{px/contagem}$, $L = 6{,}25\ \text{ms}$, resíduo $0{,}87\ \text{px}$ (244 medições).
- Eixo Y: $g = 1{,}250\ \text{px/contagem}$, $L = 6{,}00\ \text{ms}$, resíduo $0{,}86\ \text{px}$ (244 medições).

O atraso $L$ é baixo porque o cursor é lido via `GetCursorPos`; com o alvo parado, apenas o trajeto MCU → HID → Windows entra em $L$.

**Malha fechada ($K_p = 0{,}06$, $L = 6$, $g = 1{,}25$, estimador ativo):**

| Fase | Alvo válido | Overshoot | Acomodação (2%) | Regime / RMS | Atraso | `hid_drop` / `errs` |
|---|---|---|---|---|---|---|
| Degrau 500 px (`step_trim.csv`) | 100,0% (2662/2662) | 0,0% | 86 ms (máx. 97 ms) | 0,9 px | — | 0 / 0 |
| Senoide 0,5 Hz (`sine_trim.csv`) | 100,0% (2386/2386) | — | — | 31,3 px (RMS) | 47 ms | 0 / 0 |
| Rampa 300 px/s (`ramp_trim.csv`) | 100,0% (2386/2386) | — | — | 14,6 px (RMS) | 48 ms | 0 / 0 |
| Aleatório (`smooth_trim.csv`) | 100,0% (2387/2387) | — | — | 22,0 px (RMS) | 45 ms | 0 / 0 |

**Métricas operacionais do firmware:** período médio de controle de `1000,00 µs`, carga do core 1 entre `0,4%` e `0,9%` (~4–9 µs por IRQ), carga do core 0 até `4,4%`, pausa do core 1 na gravação da flash de `~24 ms` (somente em `DESLIGADO`) e atuação do failsafe em `100–103 ms`. Nos testes unitários em C (`host/tests/test_ctrl.c`), todas as 2165 verificações passaram sem falhas.
