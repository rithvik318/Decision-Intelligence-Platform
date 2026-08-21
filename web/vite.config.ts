import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev the API runs on :8000 and the app on :5173; VITE_API_BASE_URL points
// at it. In the built image both are the same origin, so the default is "".
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  build: { outDir: "dist", sourcemap: false },
});
