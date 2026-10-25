#include "weart.h"
#include <stdlib.h>
#include <string.h>
#include "driver/gpio.h"
#include "esp_camera.h"
#include "esp_heap_caps.h"
#include "sdkconfig.h"

static bool initialized;

bool board_pins_valid(void) {
#ifndef CONFIG_WEART_PINS_CONFIRMED
    return false;
#else
    int pins[] = {CONFIG_WEART_CAM_D0,CONFIG_WEART_CAM_D1,CONFIG_WEART_CAM_D2,CONFIG_WEART_CAM_D3,
        CONFIG_WEART_CAM_D4,CONFIG_WEART_CAM_D5,CONFIG_WEART_CAM_D6,CONFIG_WEART_CAM_D7,
        CONFIG_WEART_CAM_XCLK,CONFIG_WEART_CAM_PCLK,CONFIG_WEART_CAM_VSYNC,CONFIG_WEART_CAM_HREF,
        CONFIG_WEART_CAM_SDA,CONFIG_WEART_CAM_SCL,CONFIG_WEART_BUTTON,
        CONFIG_WEART_LED_R,CONFIG_WEART_LED_G,CONFIG_WEART_LED_B,CONFIG_WEART_CAM_PWDN,CONFIG_WEART_CAM_RESET};
    for (size_t i=0;i<sizeof(pins)/sizeof(pins[0]);i++) {
        if (i<15 && pins[i]<0) return false;
        if (pins[i]<0) continue;
        if (!GPIO_IS_VALID_GPIO(pins[i])) return false;
        for (size_t j=0;j<i;j++) if (pins[i]==pins[j]) return false;
    }
    int outputs[]={CONFIG_WEART_CAM_XCLK,CONFIG_WEART_CAM_SDA,CONFIG_WEART_CAM_SCL,
        CONFIG_WEART_LED_R,CONFIG_WEART_LED_G,CONFIG_WEART_LED_B,CONFIG_WEART_CAM_PWDN,CONFIG_WEART_CAM_RESET};
    for (size_t i=0;i<sizeof(outputs)/sizeof(outputs[0]);i++)
        if (outputs[i]>=0 && !GPIO_IS_VALID_OUTPUT_GPIO(outputs[i])) return false;
    return true;
#endif
}

esp_err_t camera_start(void) {
    if (initialized) return ESP_OK;
    if (!board_pins_valid() || heap_caps_get_total_size(MALLOC_CAP_SPIRAM)<2*1024*1024) return ESP_ERR_INVALID_STATE;
    camera_config_t c = {
        .pin_pwdn=CONFIG_WEART_CAM_PWDN,.pin_reset=CONFIG_WEART_CAM_RESET,
        .pin_xclk=CONFIG_WEART_CAM_XCLK,.pin_sccb_sda=CONFIG_WEART_CAM_SDA,.pin_sccb_scl=CONFIG_WEART_CAM_SCL,
        .pin_d0=CONFIG_WEART_CAM_D0,.pin_d1=CONFIG_WEART_CAM_D1,.pin_d2=CONFIG_WEART_CAM_D2,.pin_d3=CONFIG_WEART_CAM_D3,
        .pin_d4=CONFIG_WEART_CAM_D4,.pin_d5=CONFIG_WEART_CAM_D5,.pin_d6=CONFIG_WEART_CAM_D6,.pin_d7=CONFIG_WEART_CAM_D7,
        .pin_vsync=CONFIG_WEART_CAM_VSYNC,.pin_href=CONFIG_WEART_CAM_HREF,.pin_pclk=CONFIG_WEART_CAM_PCLK,
        .xclk_freq_hz=20000000,.ledc_timer=LEDC_TIMER_0,.ledc_channel=LEDC_CHANNEL_0,
        .pixel_format=PIXFORMAT_JPEG,.frame_size=FRAMESIZE_UXGA,.jpeg_quality=12,.fb_count=2,
        .fb_location=CAMERA_FB_IN_PSRAM,.grab_mode=CAMERA_GRAB_LATEST
    };
    esp_err_t err=esp_camera_init(&c);
    initialized=err==ESP_OK;
    return err;
}

esp_err_t camera_capture(uint8_t **data, size_t *length) {
    *data=NULL; *length=0;
    esp_err_t err=camera_start();
    if (err!=ESP_OK) return err;
    // Four warm-up frames; driver applies auto-exposure/white balance.
    for (int i=0;i<4;i++) {
        camera_fb_t *f=esp_camera_fb_get();
        if (!f) return ESP_FAIL;
        esp_camera_fb_return(f);
    }
    // JPEG length is only a sharpness proxy: texture/noise can increase it too.
    for (int i=0;i<3;i++) {
        if (cancel_requested) {free(*data);*data=NULL;return ESP_ERR_INVALID_STATE;}
        camera_fb_t *f=esp_camera_fb_get();
        if (!f) {free(*data);*data=NULL;return ESP_FAIL;}
        if (f->format==PIXFORMAT_JPEG && f->len>*length && f->len<=3000000) {
            uint8_t *copy=heap_caps_malloc(f->len,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
            if (!copy) {esp_camera_fb_return(f);free(*data);*data=NULL;return ESP_ERR_NO_MEM;}
            memcpy(copy,f->buf,f->len);
            free(*data);*data=copy;*length=f->len;
        }
        esp_camera_fb_return(f);
    }
    return *data ? ESP_OK : ESP_FAIL;
}

void camera_stop(void) {
    if (initialized) {esp_camera_deinit();initialized=false;}
    if (CONFIG_WEART_CAM_PWDN>=0) gpio_set_level(CONFIG_WEART_CAM_PWDN,1);
}
