import { configDefaults, defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Fred serves this application at /apps/evaluation/ (app id `evaluation`).
const prefix = "/apps/evaluation";

export default defineConfig({
  base: `${prefix}/`,
  plugins: [
    react(),
    {
      // Fred's gateway forwards the bare prefix as is; answer it like the slash form.
      name: "bare-application-path",
      configureServer(server) {
        server.middlewares.use((request, _response, next) => {
          if (request.url === prefix || request.url?.startsWith(`${prefix}?`)) {
            request.url = `${prefix}/${request.url.slice(prefix.length)}`;
          }
          next();
        });
      },
    },
  ],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    exclude: [...configDefaults.exclude],
  },
});
