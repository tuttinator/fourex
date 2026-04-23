/** @type {import('next').NextConfig} */
const nextConfig = {
	// Standalone output bundles only the files the runtime needs, which is
	// what the production Dockerfile (frontend/Dockerfile) copies into a
	// slim runner image. Safe to enable locally — ``next dev`` ignores it.
	output: "standalone",
	experimental: {
		// Enable React 19 features
		ppr: false,
	},
	reactCompiler: false,
	images: {
		remotePatterns: [
			{
				protocol: "http",
				hostname: "localhost",
			},
		],
	},
};

module.exports = nextConfig;
