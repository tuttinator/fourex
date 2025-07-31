import { readFile } from "fs/promises";
import { NextResponse } from "next/server";
import { join } from "path";

export async function GET(
	_request: Request,
	{ params }: { params: Promise<{ folder: string; filename: string }> },
) {
	try {
		const { folder, filename } = await params;

		// Security check: ensure filename is a JSON file and doesn't contain path traversal
		if (
			!filename.endsWith(".json") ||
			filename.includes("..") ||
			filename.includes("/")
		) {
			return NextResponse.json({ error: "Invalid filename" }, { status: 400 });
		}

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

		const filePath = join(logsPath, filename);

		try {
			const fileContent = await readFile(filePath, "utf-8");
			const jsonData = JSON.parse(fileContent);

			return NextResponse.json(jsonData);
		} catch (parseError) {
			console.error("Error parsing JSON file:", parseError);
			return NextResponse.json(
				{ error: "Failed to parse JSON file" },
				{ status: 500 },
			);
		}
	} catch (error) {
		console.error("Error reading log file:", error);
		return NextResponse.json(
			{ error: "Failed to read log file" },
			{ status: 500 },
		);
	}
}
