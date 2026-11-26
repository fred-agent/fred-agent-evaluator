import { configDefaults, defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Fred supplies a different browser directory for each organization's registration.
export default defineConfig({
  base: "./",
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    exclude: [...configDefaults.exclude],
  },
});
