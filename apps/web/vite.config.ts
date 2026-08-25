import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5273, // 原默认 5173 与其他项目冲突,固定改 5273
    strictPort: true, // 被占直接报错,不静默漂移到别的端口
    proxy: {
      "/api": "http://127.0.0.1:8100", // FastAPI
    },
  },
});
