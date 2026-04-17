/** @type {import('next').NextConfig} */
const nextConfig = {
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
