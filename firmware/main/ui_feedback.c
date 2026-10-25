#include "weart.h"
#include "driver/gpio.h"
#include "sdkconfig.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
static volatile device_state_t current=BOOT;
static void rgb(int r,int g,int b){
    if(CONFIG_WEART_LED_R>=0)gpio_set_level(CONFIG_WEART_LED_R,r);
    if(CONFIG_WEART_LED_G>=0)gpio_set_level(CONFIG_WEART_LED_G,g);
    if(CONFIG_WEART_LED_B>=0)gpio_set_level(CONFIG_WEART_LED_B,b);
}
static void led_task(void *arg){
    unsigned tick=0;
    while(1){
        bool blink=(tick%8)<4;
        switch(current){
            case BOOT:rgb(0,0,blink);break;
            case PROVISIONING:rgb(blink,0,blink);break;
            case CONNECTING:rgb(0,0,blink);break;
            case READY:rgb(0,1,0);break;
            case CAPTURING:rgb(1,1,1);break;
            case UPLOADING:rgb(0,blink,1);break;
            case PROCESSING:rgb(blink,blink,0);break;
            case DONE:rgb(0,1,0);break;
            case RETAKE:rgb(tick%12==0||tick%12==2,0,0);break;
            default:rgb(tick%16<8,0,0);break;
        }
        tick++;vTaskDelay(pdMS_TO_TICKS(125));
    }
}
void feedback_init(void){
    int pins[]={CONFIG_WEART_LED_R,CONFIG_WEART_LED_G,CONFIG_WEART_LED_B};
    for(int i=0;i<3;i++)if(pins[i]>=0){gpio_reset_pin(pins[i]);gpio_set_direction(pins[i],GPIO_MODE_OUTPUT);}
    xTaskCreate(led_task,"status_led",2048,NULL,2,NULL);
}
void feedback_set(device_state_t state){current=state;}
