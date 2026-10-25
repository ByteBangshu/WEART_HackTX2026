#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"

typedef enum { BOOT, PROVISIONING, CONNECTING, READY, CAPTURING, UPLOADING, PROCESSING, DONE, RETAKE, ERROR_STATE } device_state_t;
typedef struct {
    char ssid[33], password[65], host[192], device_id[65], token[96], pair_code[40], ca_pem[4096];
} device_config_t;
extern device_config_t device_config;
extern volatile bool cancel_requested;
extern volatile bool capture_busy;
esp_err_t config_load(void);
esp_err_t config_save(void);
void provisioning_start(void);
esp_err_t network_start(void);
esp_err_t network_wait(uint32_t ms);
esp_err_t pair_device(void);
esp_err_t upload_jpeg(const uint8_t *data, size_t size, const char *capture_id, char *job_id, size_t job_size);
esp_err_t poll_job(const char *job_id, char *state, size_t state_size);
esp_err_t cancel_job(const char *job_id);
esp_err_t camera_start(void);
esp_err_t camera_capture(uint8_t **data, size_t *length);
void camera_stop(void);
void feedback_init(void);
void feedback_set(device_state_t state);
bool board_pins_valid(void);
void power_idle(uint64_t idle_ms);
