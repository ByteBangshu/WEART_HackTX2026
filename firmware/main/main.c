#include "weart.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "driver/gpio.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_random.h"
#include "esp_sleep.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_task_wdt.h"
#include "esp_sntp.h"
#include "nvs_flash.h"
#include "sdkconfig.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

volatile bool cancel_requested;
volatile bool capture_busy;
static QueueHandle_t button_events;
static uint64_t last_action;
static RTC_DATA_ATTR unsigned crash_count;
static void IRAM_ATTR button_isr(void *arg){
    int level=gpio_get_level(CONFIG_WEART_BUTTON);BaseType_t wake=pdFALSE;
    xQueueSendFromISR(button_events,&level,&wake);if(wake)portYIELD_FROM_ISR();
}
static void capture_task(void *arg){
    esp_task_wdt_add(NULL);
    uint8_t *image=NULL;size_t length=0;char job[80]={0},id[40];uint8_t random[16];
    esp_fill_random(random,sizeof(random));for(int i=0;i<16;i++)snprintf(id+i*2,3,"%02x",random[i]);
    feedback_set(CAPTURING);
    esp_err_t err=camera_capture(&image,&length);
    if(err==ESP_OK && !cancel_requested){
        feedback_set(UPLOADING);
        err=upload_jpeg(image,length,id,job,sizeof(job));
    }
    if(image){memset(image,0,length);free(image);}camera_stop();
    if(err==ESP_OK && job[0]){
        feedback_set(PROCESSING);int64_t start=esp_timer_get_time();
        bool terminal=false;
        while((esp_timer_get_time()-start)<60000000LL){
            if(cancel_requested){cancel_job(job);terminal=true;feedback_set(READY);break;}
            char state[48]={0};
            if(poll_job(job,state,sizeof(state))==ESP_OK){
                if(!strcmp(state,"COMPLETE")||!strcmp(state,"COMPLETE_ORG_ONLY")){feedback_set(DONE);terminal=true;break;}
                if(!strcmp(state,"RETAKE")||!strcmp(state,"REJECTED_CARD_TYPE")){feedback_set(RETAKE);terminal=true;break;}
                if(!strcmp(state,"FAILED")||!strcmp(state,"CANCELLED")||!strcmp(state,"EXPIRED")){feedback_set(ERROR_STATE);terminal=true;break;}
            }
            vTaskDelay(pdMS_TO_TICKS(1000));
        }
        if(!terminal){cancel_job(job);feedback_set(ERROR_STATE);}
    }else feedback_set(cancel_requested?READY:ERROR_STATE);
    esp_task_wdt_delete(NULL);
    vTaskDelay(pdMS_TO_TICKS(2500));capture_busy=false;last_action=esp_timer_get_time()/1000;feedback_set(READY);vTaskDelete(NULL);
}
static void button_task(void *arg){
    int level;int64_t pressed=0,last_edge=0;
    while(1){
        if(xQueueReceive(button_events,&level,pdMS_TO_TICKS(1000))){
            int64_t now=esp_timer_get_time()/1000;
            if(now-last_edge<40)continue;last_edge=now;last_action=now;
            if(level==0)pressed=now;
            else if(pressed){
                if(now-pressed>=1500){cancel_requested=true;if(!capture_busy)feedback_set(READY);}
                else if(!capture_busy){
                    capture_busy=true;cancel_requested=false;
                    if(xTaskCreate(capture_task,"capture",16384,NULL,4,NULL)!=pdPASS){capture_busy=false;feedback_set(ERROR_STATE);}
                }
                pressed=0;
            }
        }
        power_idle(esp_timer_get_time()/1000-last_action);
    }
}
void app_main(void){
    esp_err_t nvs=nvs_flash_init();
    if(nvs!=ESP_OK){printf("NVS unavailable; erase/reprovision explicitly.\n");return;}
    ESP_ERROR_CHECK(esp_netif_init());ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_reset_reason_t reason=esp_reset_reason();
    if(reason==ESP_RST_PANIC||reason==ESP_RST_TASK_WDT||reason==ESP_RST_BROWNOUT)crash_count++;else crash_count=0;
    if(!board_pins_valid()){printf("WEART safe mode: verify pins and PSRAM in menuconfig. Camera disabled.\n");return;}
    feedback_init();
    esp_task_wdt_config_t watchdog={.timeout_ms=40000,.idle_core_mask=0,.trigger_panic=true};
    ESP_ERROR_CHECK(esp_task_wdt_reconfigure(&watchdog));
    gpio_config_t button={.pin_bit_mask=1ULL<<(CONFIG_WEART_BUTTON & 63),.mode=GPIO_MODE_INPUT,.pull_up_en=GPIO_PULLUP_ENABLE,.intr_type=GPIO_INTR_ANYEDGE};
    ESP_ERROR_CHECK(gpio_config(&button));
    bool provision=config_load()!=ESP_OK||crash_count>=3;
    if(gpio_get_level(CONFIG_WEART_BUTTON)==0){vTaskDelay(pdMS_TO_TICKS(3000));provision=provision||gpio_get_level(CONFIG_WEART_BUTTON)==0;}
    if(provision){provisioning_start();return;}
    feedback_set(CONNECTING);ESP_ERROR_CHECK(network_start());
    while(network_wait(30000)!=ESP_OK){feedback_set(ERROR_STATE);vTaskDelay(pdMS_TO_TICKS(1000));feedback_set(CONNECTING);}
    // Certificate validity checks need wall-clock time. Never disable TLS time/hostname verification.
    esp_sntp_setoperatingmode(SNTP_OPMODE_POLL);esp_sntp_setservername(0,"pool.ntp.org");esp_sntp_init();
    for(int i=0;i<30&&time(NULL)<1700000000;i++)vTaskDelay(pdMS_TO_TICKS(1000));
    if(time(NULL)<1700000000||pair_device()!=ESP_OK){feedback_set(ERROR_STATE);printf("Time sync or pairing failed; verify network and host configuration.\n");return;}
    crash_count=0;
    button_events=xQueueCreate(12,sizeof(int));ESP_ERROR_CHECK(gpio_install_isr_service(0));
    ESP_ERROR_CHECK(gpio_isr_handler_add(CONFIG_WEART_BUTTON,button_isr,NULL));
    last_action=esp_timer_get_time()/1000;feedback_set(READY);
    xTaskCreate(button_task,"button",4096,NULL,3,NULL);
}
