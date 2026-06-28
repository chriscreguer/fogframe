/*
 * fogframe — XIAO ESP32-S3 (on the Seeed EE02 board) driving a 13.3" Spectra-6
 * e-paper panel. Once a day it wakes, pulls a pre-packed 6-colour image over
 * Wi-Fi, paints it, and deep-sleeps until tomorrow.
 *
 * The image (device/frame.bin) is the RAW T133A01 4bpp buffer: 1200x1600,
 * 2 px/byte, high nibble = even (left) pixel, nibble = panel colour code
 * (0x0=W 0x2=G 0x6=R 0xB=Y 0xD=B 0xF=BK). We stream it straight into the
 * Seeed_GFX sprite buffer via drawBufferPixel() — no on-device decoding.
 *
 * Build (Arduino IDE):
 *   Board:  "XIAO_ESP32S3" (the Plus variant)
 *   PSRAM:  ENABLED   (Tools -> PSRAM: "OPI PSRAM")   <-- required, 960 KB buffer
 *   Library: Seeed_GFX installed
 *
 * On any Wi-Fi/download failure it does NOT repaint, so the panel keeps
 * yesterday's image (e-paper holds without power) and simply retries tomorrow.
 */
#include "driver.h"
#include "TFT_eSPI.h"
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>

// ---- user config ------------------------------------------------------------
static const char* WIFI_SSID = "hai :3";
static const char* WIFI_PASS = "gotigers";
static const char* IMG_URL =
    "https://raw.githubusercontent.com/chriscreguer/fogframe/main/device/frame.bin";

static const uint64_t SLEEP_SECONDS  = 24ULL * 3600;   // ~daily
static const uint32_t WIFI_TIMEOUT_MS = 30000;
// -----------------------------------------------------------------------------

static const int    PANEL_W    = 1200;
static const int    ROW_BYTES  = PANEL_W / 2;            // 600
static const size_t FRAME_BYTES = (size_t)ROW_BYTES * 1600;  // 960000

EPaper epaper;

static void deepSleepUntilTomorrow() {
  WiFi.disconnect(true);
  esp_sleep_enable_timer_wakeup(SLEEP_SECONDS * 1000000ULL);
  Serial.printf("Sleeping %llus...\n", (unsigned long long)SLEEP_SECONDS);
  esp_deep_sleep_start();
}

// Returns true only if the full frame downloaded and was painted.
static bool fetchAndPaint() {
  WiFiClientSecure client;
  client.setInsecure();                 // skip cert validation (hobby use)
  HTTPClient http;
  http.setTimeout(20000);
  if (!http.begin(client, IMG_URL)) { Serial.println("http.begin failed"); return false; }

  int code = http.GET();
  if (code != HTTP_CODE_OK) { Serial.printf("HTTP %d\n", code); http.end(); return false; }

  int len = http.getSize();             // expect 960000 (or -1 if chunked)
  Serial.printf("Content-Length: %d\n", len);
  WiFiClient* stream = http.getStreamPtr();

  uint8_t buf[1460];
  size_t idx = 0;
  uint32_t lastData = millis();
  while (http.connected() && idx < FRAME_BYTES) {
    size_t avail = stream->available();
    if (avail) {
      int r = stream->readBytes(buf, min(avail, sizeof(buf)));
      for (int i = 0; i < r && idx < FRAME_BYTES; ++i, ++idx) {
        int y  = idx / ROW_BYTES;
        int bx = idx % ROW_BYTES;
        epaper.drawBufferPixel(bx * 2, y, buf[i], 4);  // 2 px per byte
      }
      lastData = millis();
    } else {
      if (millis() - lastData > 15000) { Serial.println("stream stalled"); break; }
      delay(2);
    }
  }
  http.end();
  Serial.printf("Received %u / %u bytes\n", (unsigned)idx, (unsigned)FRAME_BYTES);
  if (idx < FRAME_BYTES) return false;

  epaper.update();                      // ~25-35s full refresh, then panel sleeps
  return true;
}

// ---- DEBUG BUILD --------------------------------------------------------
// Scans + lists visible networks, prints failure reasons, and STAYS AWAKE
// retrying on WiFi failure (so the USB port doesn't vanish and logs keep
// flowing). Once WiFi connects and the frame paints, it deep-sleeps normally.
// Set DEBUG_WIFI to 0 later for production (deep-sleep-on-failure).
#define DEBUG_WIFI 1

static const char* wifiReason(uint8_t r) {
  switch (r) {
    case 2:   return "AUTH_EXPIRE";
    case 15:  return "4WAY_HANDSHAKE_TIMEOUT (usually WRONG PASSWORD)";
    case 200: return "BEACON_TIMEOUT (weak/lost signal)";
    case 201: return "NO_AP_FOUND (too weak / not in range)";
    case 202: return "AUTH_FAIL (WRONG PASSWORD)";
    case 203: return "ASSOC_FAIL";
    case 204: return "HANDSHAKE_TIMEOUT (weak signal)";
    case 205: return "CONNECTION_FAIL";
    default:  return "(see esp_wifi_types.h)";
  }
}

static void onWiFiEvent(WiFiEvent_t event, WiFiEventInfo_t info) {
  if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) {
    uint8_t r = info.wifi_sta_disconnected.reason;
    Serial.printf("  [event] STA disconnected, reason=%u  %s\n", r, wifiReason(r));
  }
}

static void scanAndList() {
  Serial.println("Scanning for 2.4GHz networks (ESP32-S3 cannot see 5GHz)...");
  int n = WiFi.scanNetworks();
  Serial.printf("Found %d network(s):\n", n);
  bool sawTarget = false;
  for (int i = 0; i < n; i++) {
    bool match = WiFi.SSID(i) == String(WIFI_SSID);
    if (match) sawTarget = true;
    Serial.printf("  %2d: '%s'%s  RSSI=%ddBm  ch=%d  enc=%d\n",
                  i, WiFi.SSID(i).c_str(), match ? "  <-- TARGET" : "",
                  WiFi.RSSI(i), WiFi.channel(i), (int)WiFi.encryptionType(i));
  }
  Serial.printf("Target SSID '%s' %s in scan.\n",
                WIFI_SSID, sawTarget ? "FOUND" : "NOT FOUND (wrong name or 5GHz-only)");
}

void setup() {
  Serial.begin(115200);
  delay(400);
  Serial.println("\nfogframe waking (debug build)");

  epaper.begin();                       // allocates the 960 KB 4bpp sprite (PSRAM)

  WiFi.mode(WIFI_STA);
  WiFi.onEvent(onWiFiEvent);             // prints exact disconnect reason
  WiFi.disconnect(true);
  delay(100);
  scanAndList();

  for (int attempt = 1; ; attempt++) {
    Serial.printf("Connecting to '%s' (attempt %d)...\n", WIFI_SSID, attempt);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    uint32_t t0 = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - t0 < WIFI_TIMEOUT_MS) delay(250);

    if (WiFi.status() == WL_CONNECTED) {
      Serial.printf("WiFi ok: %s\n", WiFi.localIP().toString().c_str());
      if (fetchAndPaint()) Serial.println("painted new frame");
      else                 Serial.println("fetch failed — keeping previous image");
      deepSleepUntilTomorrow();         // success path: sleep ~24h
    }

    Serial.printf("WiFi failed (status=%d).\n", WiFi.status());
#if DEBUG_WIFI
    Serial.println("Staying awake; retrying in 8s (port stays alive)...");
    delay(8000);
#else
    deepSleepUntilTomorrow();
#endif
  }
}

void loop() {}
