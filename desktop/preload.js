"use strict";
const { contextBridge, ipcRenderer } = require("electron");

// 웹 화면(web/)에서 window.desktop으로 쓴다. 브라우저로 열면 없다
contextBridge.exposeInMainWorld("desktop", {
  version: (process.argv.find((a) => a.startsWith("--app-version=")) || "").split("=")[1] || "",
  checkForUpdates: () => ipcRenderer.invoke("update:check"),
  installUpdate: () => ipcRenderer.send("update:install"),
  onUpdate: (cb) => {
    const h = (_e, s) => cb(s);
    ipcRenderer.on("update", h);
    ipcRenderer.invoke("update:state").then(cb);
    return () => ipcRenderer.removeListener("update", h);
  },
  openExternal: (url) => ipcRenderer.send("open-external", url),
  getOpenAtLogin: () => ipcRenderer.invoke("login-item:get"),
  setOpenAtLogin: (on) => ipcRenderer.invoke("login-item:set", on),
  onSplash: (cb) => ipcRenderer.on("splash", (_e, m) => cb(m)),
  onOverlay: (cb) => ipcRenderer.on("overlay", (_e, d) => cb(d)),
});
