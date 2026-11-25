# Testes unitarios do firmware (parte portavel em C) compilado no PC.
#   make -f tests.mk test   -> compila e executa test_ctrl
FW   = ../../firmware/src
SRCS = $(FW)/ctrl/pid.c $(FW)/ctrl/estimator.c $(FW)/ctrl/params.c $(FW)/ctrl/loop.c \
       $(FW)/proto/proto.c $(FW)/proto/crc8.c $(FW)/app/app.c sil_shim.c
CFLAGS = -std=gnu11 -O1 -g -Wall -Wextra

ifneq ($(OS),Windows_NT)
CFLAGS += -fsanitize=undefined -fno-sanitize-recover=undefined
endif

test: test_ctrl
	./test_ctrl

test_ctrl: test_ctrl.c $(SRCS)
	$(CC) $(CFLAGS) $^ -o $@

clean:
	rm -f test_ctrl test_ctrl.exe

.PHONY: test clean
