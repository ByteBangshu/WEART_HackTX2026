#include "weart.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "nvs.h"
#include "esp_http_server.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_random.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "cJSON.h"

device_config_t device_config;
esp_err_t config_load(void) {
    nvs_handle_t h;esp_err_t err=nvs_open("weart",NVS_READONLY,&h);if(err!=ESP_OK)return err;
    size_t length=sizeof(device_config);err=nvs_get_blob(h,"config",&device_config,&length);nvs_close(h);
    if(err!=ESP_OK || length!=sizeof(device_config))return ESP_FAIL;
    return device_config.ssid[0]&&device_config.host[0]?ESP_OK:ESP_FAIL;
}
esp_err_t config_save(void) {
    nvs_handle_t h;esp_err_t err=nvs_open("weart",NVS_READWRITE,&h);if(err!=ESP_OK)return err;
    err=nvs_set_blob(h,"config",&device_config,sizeof(device_config));
    if(err==ESP_OK)err=nvs_commit(h);
    nvs_close(h);
    return err;
}
static const char PAGE[]= "<!doctype html><meta name='viewport' content='width=device-width'><title>WEART setup</title>"
"<style>body{font:16px system-ui;max-width:540px;margin:30px auto;padding:15px;background:#eff3e7;color:#213b2c}input,textarea,button{display:block;width:100%;box-sizing:border-box;padding:12px;margin:8px 0 20px}textarea{height:130px}</style>"
"<h1>WEART camera setup</h1><p>Use a trusted 2.4 GHz network. The host certificate is required.</p><form id='f'>"
"<label>Wi-Fi SSID<input name='ssid' maxlength='32' required></label><label>Wi-Fi password<input name='password' type='password' maxlength='64' required></label>"
"<label>Host URL (https://IP:8765)<input name='host' maxlength='180' required></label><label>Device ID<input name='device_id' value='badge-camera' maxlength='64' required></label>"
"<label>One-time pairing code<input name='pair_code' maxlength='32' required></label><label>Host CA certificate (PEM)<textarea name='ca_pem' maxlength='4095' required></textarea></label><button>Save and connect</button></form><p id='result'></p>"
"<script>document.getElementById('f').onsubmit=async(e)=>{e.preventDefault();const r=await fetch('/configure',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});document.getElementById('result').textContent=await r.text();};</script>";
static esp_err_t page(httpd_req_t *req){httpd_resp_set_type(req,"text/html");httpd_resp_set_hdr(req,"Cache-Control","no-store");return httpd_resp_send(req,PAGE,HTTPD_RESP_USE_STRLEN);}
static void reboot_task(void *arg){vTaskDelay(pdMS_TO_TICKS(1500));esp_restart();}
static bool copy_field(cJSON *json,const char *name,char *dest,size_t capacity){
    cJSON *item=cJSON_GetObjectItemCaseSensitive(json,name);
    if(!cJSON_IsString(item)||strlen(item->valuestring)>=capacity)return false;
    strlcpy(dest,item->valuestring,capacity);return true;
}
static esp_err_t configure(httpd_req_t *req) {
    if(req->content_len>6000 || req->content_len<2)return httpd_resp_send_err(req,HTTPD_400_BAD_REQUEST,"Invalid configuration");
    char *text=calloc(req->content_len+1,1);if(!text)return ESP_ERR_NO_MEM;
    int got=0;
    while(got<req->content_len){int n=httpd_req_recv(req,text+got,req->content_len-got);if(n<=0){free(text);return ESP_FAIL;}got+=n;}
    cJSON *json=cJSON_Parse(text);memset(text,0,req->content_len);free(text);
    device_config_t next={0};
    bool ok=copy_field(json,"ssid",next.ssid,sizeof(next.ssid))&&copy_field(json,"password",next.password,sizeof(next.password))&&
        copy_field(json,"host",next.host,sizeof(next.host))&&copy_field(json,"device_id",next.device_id,sizeof(next.device_id))&&
        copy_field(json,"pair_code",next.pair_code,sizeof(next.pair_code))&&copy_field(json,"ca_pem",next.ca_pem,sizeof(next.ca_pem));
    cJSON_Delete(json);
    if(!ok||!next.ssid[0]||strlen(next.password)<8||strncmp(next.host,"https://",8)!=0||!strstr(next.ca_pem,"BEGIN CERTIFICATE"))
        return httpd_resp_send_err(req,HTTPD_400_BAD_REQUEST,"Check SSID, password, HTTPS host and certificate");
    size_t n=strlen(next.host);if(next.host[n-1]=='/')next.host[n-1]=0;
    device_config=next;memset(&next,0,sizeof(next));
    if(config_save()!=ESP_OK)return httpd_resp_send_err(req,HTTPD_500_INTERNAL_SERVER_ERROR,"Could not save configuration");
    httpd_resp_sendstr(req,"Saved. Camera is restarting; reconnect your phone to the host network.");
    xTaskCreate(reboot_task,"reboot",2048,NULL,2,NULL);return ESP_OK;
}
void provisioning_start(void) {
    esp_netif_create_default_wifi_ap();wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();ESP_ERROR_CHECK(esp_wifi_init(&init));
    uint8_t random[8];esp_fill_random(random,sizeof(random));char password[17];
    for(int i=0;i<8;i++)snprintf(password+i*2,3,"%02x",random[i]);
    wifi_config_t wifi={0};strlcpy((char*)wifi.ap.ssid,"WEART-Setup",sizeof(wifi.ap.ssid));
    strlcpy((char*)wifi.ap.password,password,sizeof(wifi.ap.password));wifi.ap.authmode=WIFI_AUTH_WPA2_PSK;wifi.ap.max_connection=1;
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_AP));ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP,&wifi));ESP_ERROR_CHECK(esp_wifi_start());
    // Physical USB commissioning only; never prints Wi-Fi credentials, device token, or model key.
    printf("WEART setup AP password (one boot): %s\nOpen http://192.168.4.1\n",password);
    memset(password,0,sizeof(password));
    httpd_config_t cfg=HTTPD_DEFAULT_CONFIG();cfg.stack_size=12288;cfg.recv_wait_timeout=5;cfg.max_open_sockets=2;
    httpd_handle_t server=NULL;ESP_ERROR_CHECK(httpd_start(&server,&cfg));
    httpd_uri_t root={.uri="/",.method=HTTP_GET,.handler=page};httpd_uri_t post={.uri="/configure",.method=HTTP_POST,.handler=configure};
    httpd_register_uri_handler(server,&root);httpd_register_uri_handler(server,&post);
    feedback_set(PROVISIONING);
}
