import { readdir, stat } from "fs/promises";
import { NextResponse } from "next/server";
import { join } from "path";

export async function GET(
	_request: Request,
	{ params }: { params: Promise<{ folder: string }> },
) {
	try {
		const { folder } = await params;

		// Determine the base path for logs
		const projectRoot = process.cwd().includes("frontend")
			? join(process.cwd(), "..")
			: process.cwd();

		let logsPath: string;

		if (folder === "root") {
			logsPath = join(projectRoot, "logs");
		} else if (folder === "agents") {
			logsPath = join(projectRoot, "agents", "logs");
		} else {
			return NextResponse.json({ error: "Invalid folder" }, { status: 400 });
		}

		// Read directory contents
		const files = await readdir(logsPath);

		// Filter for JSON files and get file stats
		const jsonFiles = files.filter((file) => file.endsWith(".json"));

		const fileDetails = await Promise.all(
			jsonFiles.map(async (file) => {
				const filePath = join(logsPath, file);
				const stats = await stat(filePath);

				return {
					name: file,
					path: filePath,
					size: stats.size,
					modified: stats.mtime.toISOString(),
					type: file.includes("turn_") ? "turn" : "game",
				};
			}),
		);

		// Sort by modification time (newest first)
		fileDetails.sort(
			(a, b) => new Date(b.modified).getTime() - new Date(a.modified).getTime(),
		);

		return NextResponse.json({
			files: fileDetails,
			folder,
			count: fileDetails.length,
		});
	} catch (error) {
		console.error("Error reading logs directory:", error);
		return NextResponse.json(
			{ error: "Failed to read logs directory" },
			{ status: 500 },
		);
	}
}
