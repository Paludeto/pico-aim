/* Descritores USB: dispositivo composto com CDC-ACM (link com o PC) e HID
 * (mouse relativo). Spec 6.2. */
#include <string.h>
#include "tusb.h"
#include "pico/unique_id.h"
#include "board_config.h"

/* ---------------- Dispositivo ---------------- */
/* Classe "Miscellaneous / IAD": necessaria porque a funcao CDC ocupa duas
 * interfaces, agrupadas por um Interface Association Descriptor. */
static const tusb_desc_device_t desc_device = {
    .bLength            = sizeof(tusb_desc_device_t),
    .bDescriptorType    = TUSB_DESC_DEVICE,
    .bcdUSB             = 0x0200,
    .bDeviceClass       = TUSB_CLASS_MISC,
    .bDeviceSubClass    = MISC_SUBCLASS_COMMON,
    .bDeviceProtocol    = MISC_PROTOCOL_IAD,
    .bMaxPacketSize0    = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor           = USB_VID,
    .idProduct          = USB_PID,
    .bcdDevice          = USB_BCD_DEVICE,
    .iManufacturer      = 1,
    .iProduct           = 2,
    .iSerialNumber      = 3,
    .bNumConfigurations = 1
};

uint8_t const *tud_descriptor_device_cb(void)
{
    return (uint8_t const *)&desc_device;
}

/* ---------------- HID ---------------- */
/* Mouse sem report ID: botoes, X e Y relativos (int8), roda vertical e
 * horizontal. E o formato de tud_hid_mouse_report(). */
static const uint8_t desc_hid_report[] = {
    TUD_HID_REPORT_DESC_MOUSE()
};

uint8_t const *tud_hid_descriptor_report_cb(uint8_t instance)
{
    (void)instance;
    return desc_hid_report;
}

/* ---------------- Configuracao ---------------- */
enum { ITF_NUM_CDC = 0, ITF_NUM_CDC_DATA, ITF_NUM_HID, ITF_NUM_TOTAL };

#define EPNUM_CDC_NOTIF 0x81
#define EPNUM_CDC_OUT   0x02
#define EPNUM_CDC_IN    0x82
#define EPNUM_HID       0x83

#define CONFIG_TOTAL_LEN (TUD_CONFIG_DESC_LEN + TUD_CDC_DESC_LEN + TUD_HID_DESC_LEN)

static const uint8_t desc_configuration[] = {
    /* 1 configuracao, alimentada pelo barramento, 100 mA */
    TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 100),
    /* CDC-ACM: notificacao (interrupt IN, 8 bytes) + dados (bulk OUT/IN, 64 bytes) */
    TUD_CDC_DESCRIPTOR(ITF_NUM_CDC, 4, EPNUM_CDC_NOTIF, 8, EPNUM_CDC_OUT, EPNUM_CDC_IN, 64),
    /* HID: interrupt IN, bInterval = 1 (1 ms em full-speed) */
    TUD_HID_DESCRIPTOR(ITF_NUM_HID, 5, HID_ITF_PROTOCOL_NONE, sizeof(desc_hid_report),
                       EPNUM_HID, CFG_TUD_HID_EP_BUFSIZE, 1)
};

uint8_t const *tud_descriptor_configuration_cb(uint8_t index)
{
    (void)index;
    return desc_configuration;
}

/* ---------------- Strings ---------------- */
static const char *const string_desc[] = {
    NULL,                       /* 0: idioma */
    USB_STR_MANUFACTURER,       /* 1 */
    USB_STR_PRODUCT,            /* 2 */
    NULL,                       /* 3: numero de serie (ID unico da flash) */
    USB_STR_CDC,                /* 4 */
    USB_STR_HID                 /* 5 */
};

uint16_t const *tud_descriptor_string_cb(uint8_t index, uint16_t langid)
{
    static uint16_t desc[1 + 32];
    char serial[2 * PICO_UNIQUE_BOARD_ID_SIZE_BYTES + 1];
    const char *str;
    uint8_t n;
    (void)langid;

    if (index == 0) {
        desc[1] = 0x0409;       /* ingles (EUA) */
        n = 1;
    } else {
        if (index >= sizeof string_desc / sizeof string_desc[0])
            return NULL;
        if (index == 3) {
            pico_get_unique_board_id_string(serial, sizeof serial);
            str = serial;
        } else {
            str = string_desc[index];
        }
        size_t len = strlen(str);
        if (len > 32)
            len = 32;
        for (n = 0; n < len; n++)
            desc[1 + n] = (uint16_t)(unsigned char)str[n];     /* ASCII -> UTF-16LE */
    }
    desc[0] = (uint16_t)((TUSB_DESC_STRING << 8) | (2 * n + 2));
    return desc;
}

/* ---------------- Callbacks HID obrigatorios ---------------- */
uint16_t tud_hid_get_report_cb(uint8_t instance, uint8_t report_id, hid_report_type_t report_type,
                               uint8_t *buffer, uint16_t reqlen)
{
    (void)instance; (void)report_id; (void)report_type; (void)buffer; (void)reqlen;
    return 0;                   /* STALL: o mouse nao tem relatorio sob demanda */
}

void tud_hid_set_report_cb(uint8_t instance, uint8_t report_id, hid_report_type_t report_type,
                           uint8_t const *buffer, uint16_t bufsize)
{
    (void)instance; (void)report_id; (void)report_type; (void)buffer; (void)bufsize;
}
