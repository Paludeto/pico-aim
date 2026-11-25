#include "crc8.h"

uint8_t crc8_update(uint8_t crc, uint8_t data)
{
    crc ^= data;
    for (uint8_t i = 0; i < 8; i++)
        crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
    return crc;
}

uint8_t crc8(const uint8_t *buf, uint8_t len)
{
    uint8_t crc = 0;
    while (len--)
        crc = crc8_update(crc, *buf++);
    return crc;
}
