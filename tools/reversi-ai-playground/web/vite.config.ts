import { defineConfig } from "vite";

export default defineConfig({
  server: {
    host: "127.0.0.1",
    port: Number(process.env.PLAYGROUND_WEB_PORT ?? 5173),
    proxy: { "/ws": { target: `ws://127.0.0.1:${process.env.PLAYGROUND_PORT ?? 8787}`, ws: true } },
  },
});
