#ifndef CRC8_H
#define CRC8_H
#include <stdint.h>
/* CRC-8, polinomio 0x07, valor inicial 0x00, sem reflexao. */
uint8_t crc8_update(uint8_t crc, uint8_t data);
uint8_t crc8(const uint8_t *buf, uint8_t len);
#endif
