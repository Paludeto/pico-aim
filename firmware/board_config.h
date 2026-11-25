/* Configuracao central da placa: pinagem, taxas e identificacao USB.
 * Raspberry Pi Pico (RP2040), sem nenhum componente externo. */
#ifndef BOARD_CONFIG_H
#define BOARD_CONFIG_H

/* ---------------- Pinagem ---------------- */
#define LED_PIN        25u      /* LED onboard */
/* Pinos de debug (so para osciloscopio/analisador logico; nada e ligado). */
#define DBG_PIN_CTRL   2u       /* GP2: alto durante o passo de controle (core 1) */
#define DBG_PIN_HID    3u       /* GP3: alterna a cada relatorio HID enviado (core 0) */
/* O botao BOOTSEL nao tem GPIO: e lido pelo CS da flash QSPI (ui/bootsel.c). */

/* ---------------- Temporizacao ---------------- */
#define CTRL_PERIOD_US     1000u    /* alarme de hardware do core 1: 1 kHz */
#define UI_SCAN_MS         10u      /* varredura do BOOTSEL + padroes do LED */
#define BTN_DEBOUNCE_SCANS 3u       /* 30 ms */
#define BTN_LONG_MS        1000u    /* pressao longa: parada de emergencia */
#define WATCHDOG_MS        1000u    /* cobre o apagamento de um setor da flash */

/* ---------------- Filas entre os nucleos ---------------- */
#define Q_MEAS_LEN   4u
#define Q_CMD_LEN    2u
#define Q_U_LEN      16u
#define Q_TELEM_LEN  8u
/* Movimento pendente no core 0 quando o host nao consome o HID a tempo:
 * os comandos sao somados ate este limite (contagens por eixo). */
#define HID_PENDING_MAX 32767

/* ---------------- USB ---------------- */
#define USB_VID 0x1209          /* pid.codes */
#define USB_PID 0x0001          /* PID de teste do pid.codes: uso didatico, nao distribuir */
#define USB_BCD_DEVICE 0x0100
#define USB_STR_MANUFACTURER "UTFPR Apucarana"
#define USB_STR_PRODUCT      "UTFPR Cursor Tracker"
#define USB_STR_CDC          "Cursor Tracker - link (CDC)"
#define USB_STR_HID          "Cursor Tracker - mouse (HID)"

#endif
