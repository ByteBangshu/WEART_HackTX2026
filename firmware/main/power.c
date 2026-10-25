#include "weart.h"
#include "sdkconfig.h"
#include "esp_sleep.h"
#include "driver/rtc_io.h"
#include "driver/gpio.h"

void power_idle(uint64_t idle_ms){
    if(idle_ms<60000 || capture_busy)return;
    camera_stop();
#ifdef CONFIG_WEART_DEEP_SLEEP
    if(idle_ms>=300000 && rtc_gpio_is_valid_gpio(CONFIG_WEART_BUTTON)){
        esp_sleep_enable_ext1_wakeup(1ULL<<CONFIG_WEART_BUTTON,ESP_EXT1_WAKEUP_ANY_LOW);
        rtc_gpio_pullup_en(CONFIG_WEART_BUTTON);rtc_gpio_pulldown_dis(CONFIG_WEART_BUTTON);
        esp_deep_sleep_start();
    }
#endif
    // Camera shutdown plus Wi-Fi modem sleep preserves responsive button/network handling.
    // Full light sleep requires board-specific wake validation and is not enabled blindly.
}
