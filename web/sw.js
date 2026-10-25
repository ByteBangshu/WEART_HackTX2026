"use strict";
const CACHE="weart-shell-v2";
const STATIC=["/","/styles.css","/app.js","/icon.svg","/manifest.webmanifest"];
self.addEventListener("install",event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(STATIC))));
self.addEventListener("activate",event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k))))));
self.addEventListener("fetch",event=>{const url=new URL(event.request.url);if(event.request.method!=="GET"||url.origin!==self.location.origin||!STATIC.includes(url.pathname))return;event.respondWith(fetch(event.request).catch(()=>caches.match(event.request)));});
