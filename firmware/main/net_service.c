#include "weart.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "esp_event.h"
#include "esp_http_client.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "esp_timer.h"
#include "esp_task_wdt.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "cJSON.h"
#include "esp_sntp.h"

static EventGroupHandle_t wifi_events;
static unsigned retry_count;
static void reconnect_task(void *arg) {
    unsigned backoff=1U << (retry_count<5 ? retry_count : 5);
    vTaskDelay(pdMS_TO_TICKS(backoff*1000));
    esp_wifi_connect();vTaskDelete(NULL);
}
static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    if (base==IP_EVENT && id==IP_EVENT_STA_GOT_IP) {retry_count=0;xEventGroupSetBits(wifi_events,1);}
    else if (base==WIFI_EVENT && id==WIFI_EVENT_STA_START) esp_wifi_connect();
    else if (base==WIFI_EVENT && id==WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(wifi_events,1);retry_count++;
        xTaskCreate(reconnect_task,"wifi_retry",3072,NULL,3,NULL);
    }
}
esp_err_t network_start(void) {
    wifi_events=xEventGroupCreate();
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&init));
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT,ESP_EVENT_ANY_ID,wifi_event,NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,IP_EVENT_STA_GOT_IP,wifi_event,NULL));
    wifi_config_t config={0};
    strlcpy((char *)config.sta.ssid,device_config.ssid,sizeof(config.sta.ssid));
    strlcpy((char *)config.sta.password,device_config.password,sizeof(config.sta.password));
    config.sta.threshold.authmode=WIFI_AUTH_WPA2_PSK;
    config.sta.pmf_cfg.capable=true;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA,&config));
    ESP_ERROR_CHECK(esp_wifi_start());
    esp_wifi_set_ps(WIFI_PS_MIN_MODEM);
    return ESP_OK;
}
esp_err_t network_wait(uint32_t ms) {
    return (xEventGroupWaitBits(wifi_events,1,pdFALSE,pdFALSE,pdMS_TO_TICKS(ms))&1) ? ESP_OK : ESP_ERR_TIMEOUT;
}
typedef struct {char *text;size_t used,cap;bool overflow;} response_t;
static esp_err_t http_event(esp_http_client_event_t *evt) {
    response_t *r=evt->user_data;
    if(evt->event_id==HTTP_EVENT_ON_DATA && evt->data_len>0) {
        if(r->used+(size_t)evt->data_len>=r->cap){r->overflow=true;return ESP_FAIL;}
        memcpy(r->text+r->used,evt->data,evt->data_len);r->used+=evt->data_len;r->text[r->used]=0;
    }
    return ESP_OK;
}
static esp_err_t request(const char *path,esp_http_client_method_t method,const void *body,size_t len,
                         const char *capture,response_t *response,int *status) {
    if (strncmp(device_config.host,"https://",8)!=0 || !strstr(device_config.ca_pem,"BEGIN CERTIFICATE")) return ESP_ERR_INVALID_ARG;
    char url[320],auth[128];snprintf(url,sizeof(url),"%s%s",device_config.host,path);
    esp_http_client_config_t cfg={.url=url,.cert_pem=device_config.ca_pem,.timeout_ms=15000,
        .event_handler=http_event,.user_data=response,.buffer_size=2048,.disable_auto_redirect=true};
    esp_http_client_handle_t client=esp_http_client_init(&cfg);
    if(!client)return ESP_ERR_NO_MEM;
    esp_http_client_set_method(client,method);
    esp_http_client_set_header(client,"X-Device-ID",device_config.device_id);
    if(device_config.token[0]) {snprintf(auth,sizeof(auth),"Bearer %s",device_config.token);esp_http_client_set_header(client,"Authorization",auth);}
    if(capture) {
        esp_http_client_set_header(client,"X-Capture-ID",capture);
        esp_http_client_set_header(client,"X-Firmware-Version","0.1.0");
        esp_http_client_set_header(client,"X-Resolution","1600x1200");
    }
    if(body) {
        esp_http_client_set_header(client,"Content-Type",capture?"image/jpeg":"application/json");
        esp_http_client_set_post_field(client,body,(int)len);
    }
    if(esp_task_wdt_status(NULL)==ESP_OK)esp_task_wdt_reset();
    esp_err_t err=esp_http_client_perform(client);
    if(esp_task_wdt_status(NULL)==ESP_OK)esp_task_wdt_reset();
    *status=esp_http_client_get_status_code(client);
    esp_http_client_cleanup(client);
    if(response->overflow)return ESP_ERR_INVALID_SIZE;
    return err;
}
esp_err_t pair_device(void) {
    if(device_config.token[0]) return ESP_OK;
    cJSON *body=cJSON_CreateObject();cJSON_AddStringToObject(body,"device_id",device_config.device_id);
    cJSON_AddStringToObject(body,"code",device_config.pair_code);
    char *json=cJSON_PrintUnformatted(body);char text[1024]={0};response_t response={text,0,sizeof(text),false};int status=0;
    esp_err_t err=request("/v1/devices/pair",HTTP_METHOD_POST,json,strlen(json),NULL,&response,&status);
    cJSON_Delete(body);free(json);
    if(err!=ESP_OK || status!=200){printf("Pair request failed (transport=%s, HTTP=%d).\n",esp_err_to_name(err),status);return ESP_FAIL;}
    cJSON *parsed=cJSON_Parse(text);const cJSON *token=cJSON_GetObjectItemCaseSensitive(parsed,"token");
    if(!cJSON_IsString(token) || strlen(token->valuestring)>=sizeof(device_config.token)){cJSON_Delete(parsed);return ESP_FAIL;}
    strlcpy(device_config.token,token->valuestring,sizeof(device_config.token));
    memset(device_config.pair_code,0,sizeof(device_config.pair_code));cJSON_Delete(parsed);memset(text,0,sizeof(text));
    return config_save();
}
esp_err_t upload_jpeg(const uint8_t *data,size_t size,const char *capture,char *job_id,size_t job_size) {
    for(int attempt=0;attempt<3;attempt++) {
        char text[1024]={0};response_t response={text,0,sizeof(text),false};int status=0;
        esp_err_t err=request("/v1/captures",HTTP_METHOD_POST,data,size,capture,&response,&status);
        if(err==ESP_OK && status==202) {
            cJSON *parsed=cJSON_Parse(text);const cJSON *id=cJSON_GetObjectItemCaseSensitive(parsed,"job_id");
            bool ok=cJSON_IsString(id)&&strlen(id->valuestring)<job_size;
            if(ok)strlcpy(job_id,id->valuestring,job_size);
            cJSON_Delete(parsed);return ok?ESP_OK:ESP_FAIL;
        }
        if(status==401 || status==403 || status==413 || status==415) return ESP_FAIL;
        if(cancel_requested)return ESP_ERR_INVALID_STATE;
        vTaskDelay(pdMS_TO_TICKS((attempt+1)*1500));
    }
    return ESP_FAIL;
}
esp_err_t poll_job(const char *job_id,char *state,size_t state_size) {
    char path[100],text[2048]={0};snprintf(path,sizeof(path),"/v1/jobs/%s",job_id);
    response_t response={text,0,sizeof(text),false};int status=0;
    esp_err_t err=request(path,HTTP_METHOD_GET,NULL,0,NULL,&response,&status);
    if(status==404){strlcpy(state,"EXPIRED",state_size);return ESP_OK;}
    if(err!=ESP_OK || status!=200)return ESP_FAIL;
    cJSON *parsed=cJSON_Parse(text);const cJSON *s=cJSON_GetObjectItemCaseSensitive(parsed,"state");
    bool ok=cJSON_IsString(s)&&strlen(s->valuestring)<state_size;
    if(ok)strlcpy(state,s->valuestring,state_size);
    cJSON_Delete(parsed);return ok?ESP_OK:ESP_FAIL;
}
esp_err_t cancel_job(const char *job_id) {
    char path[110],text[256]={0};snprintf(path,sizeof(path),"/v1/jobs/%s/cancel",job_id);
    response_t response={text,0,sizeof(text),false};int status=0;
    esp_err_t err=request(path,HTTP_METHOD_POST,NULL,0,NULL,&response,&status);
    return err==ESP_OK&&status==200?ESP_OK:ESP_FAIL;
}
