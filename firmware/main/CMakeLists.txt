idf_component_register(SRCS "main.c" "camera_service.c" "net_service.c" "provisioning.c" "ui_feedback.c" "power.c"
    INCLUDE_DIRS "." REQUIRES esp_wifi esp_event esp_netif nvs_flash esp_http_client esp_http_server json driver esp_timer esp_system esp_hw_support lwip esp32-camera)
