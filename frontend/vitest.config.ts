import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
	plugins: [react()],
	test: {
		environment: "jsdom",
		setupFiles: ["./src/__tests__/setup.ts"],
		// next-auth does `import "next/server"` which Next 16 ships without
		// a conditional-exports entry that vitest's node resolver accepts.
		// Inline the package so vite's resolver (which honours our alias
		// below) handles it instead of Node's stricter ESM resolver.
		server: {
			deps: {
				inline: ["next-auth", "@auth/core"],
			},
		},
	},
	resolve: {
		alias: {
			"@": path.resolve(__dirname, "./src"),
			// Next 16 ships `next/server` as `server.js` without a
			// `package.json` exports entry the vitest resolver accepts;
			// alias it so `next-auth`'s internals can load under vitest.
			"next/server": path.resolve(
				__dirname,
				"./node_modules/next/server.js"
			),
		},
	},
});
