"use client";

import { Calendar, Clock, FileText, Search, User } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { LogViewer } from "@/components/log-viewer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardDescription,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

interface LogFile {
	name: string;
	path: string;
	size: number;
	modified: string;
	type: "turn" | "game";
}

interface LogContent {
	filename: string;
	content: unknown;
}

export default function LogsPage() {
	const [rootLogs, setRootLogs] = useState<LogFile[]>([]);
	const [agentLogs, setAgentLogs] = useState<LogFile[]>([]);
	const [selectedLog, setSelectedLog] = useState<LogContent | null>(null);
	const [loading, setLoading] = useState(false);
	const [searchTerm, setSearchTerm] = useState("");
	const [activeTab, setActiveTab] = useState("root");

	const fetchLogs = useCallback(async (folder: "root" | "agents") => {
		try {
			const response = await fetch(`/api/logs/${folder}`);
			const data = await response.json();

			if (folder === "root") {
				setRootLogs(data.files || []);
			} else {
				setAgentLogs(data.files || []);
			}
		} catch (error) {
			console.error(`Failed to fetch ${folder} logs:`, error);
		}
	}, []);

	const loadLogFile = async (filename: string, folder: "root" | "agents") => {
		setLoading(true);
		try {
			const response = await fetch(
				`/api/logs/${folder}/${encodeURIComponent(filename)}`,
			);
			const data = await response.json();
			setSelectedLog({ filename, content: data });
		} catch (error) {
			console.error("Failed to load log file:", error);
		} finally {
			setLoading(false);
		}
	};

	useEffect(() => {
		fetchLogs("root");
		fetchLogs("agents");
	}, [fetchLogs]);

	const filterLogs = (logs: LogFile[]) => {
		if (!searchTerm) return logs;
		return logs.filter((log) =>
			log.name.toLowerCase().includes(searchTerm.toLowerCase()),
		);
	};

	const formatFileSize = (bytes: number) => {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	};

	const parseLogType = (filename: string) => {
		if (filename.includes("turn_")) return "turn";
		if (filename.includes("game_log_")) return "game";
		return "unknown";
	};

	const parseGameId = (filename: string) => {
		const match = filename.match(/(?:turn_|game_log_)([^_]+)/);
		return match ? match[1] : "unknown";
	};

	const parsePlayer = (filename: string) => {
		const match = filename.match(/_(\w+)\.json$/);
		return match ? match[1] : null;
	};

	const LogFileCard = ({
		log,
		folder,
	}: {
		log: LogFile;
		folder: "root" | "agents";
	}) => {
		const logType = parseLogType(log.name);
		const gameId = parseGameId(log.name);
		const player = parsePlayer(log.name);

		return (
			<Card
				className="cursor-pointer hover:bg-accent transition-colors"
				onClick={() => loadLogFile(log.name, folder)}
			>
				<CardHeader className="pb-2">
					<div className="flex items-center justify-between">
						<CardTitle className="text-sm font-medium flex items-center gap-2">
							<FileText className="w-4 h-4" />
							{log.name}
						</CardTitle>
						<Badge variant={logType === "turn" ? "default" : "secondary"}>
							{logType}
						</Badge>
					</div>
					<CardDescription className="text-xs">
						Game: {gameId}
						{player && (
							<>
								{" • "}
								<span className="inline-flex items-center gap-1">
									<User className="w-3 h-3" />
									{player}
								</span>
							</>
						)}
					</CardDescription>
				</CardHeader>
				<CardContent className="pt-0">
					<div className="flex items-center justify-between text-xs text-muted-foreground">
						<span className="flex items-center gap-1">
							<Clock className="w-3 h-3" />
							{formatFileSize(log.size)}
						</span>
						<span className="flex items-center gap-1">
							<Calendar className="w-3 h-3" />
							{new Date(log.modified).toLocaleDateString()}
						</span>
					</div>
				</CardContent>
			</Card>
		);
	};

	return (
		<div className="container mx-auto p-6 space-y-6">
			<div className="flex items-center justify-between">
				<div>
					<h1 className="text-3xl font-bold">Game Logs</h1>
					<p className="text-muted-foreground">
						Browse and analyze game turn logs and agent logs
					</p>
				</div>
				<Button
					onClick={() => {
						fetchLogs("root");
						fetchLogs("agents");
					}}
				>
					Refresh
				</Button>
			</div>

			<div className="flex gap-6">
				<div className="w-1/3 space-y-4">
					<div className="relative">
						<Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground w-4 h-4" />
						<Input
							placeholder="Search logs..."
							value={searchTerm}
							onChange={(e) => setSearchTerm(e.target.value)}
							className="pl-10"
						/>
					</div>

					<Tabs value={activeTab} onValueChange={setActiveTab}>
						<TabsList className="grid w-full grid-cols-2">
							<TabsTrigger value="root">
								Game Logs ({rootLogs.length})
							</TabsTrigger>
							<TabsTrigger value="agents">
								Agent Logs ({agentLogs.length})
							</TabsTrigger>
						</TabsList>

						<TabsContent value="root" className="mt-4">
							<ScrollArea className="h-[600px]">
								<div className="space-y-2">
									{filterLogs(rootLogs).map((log) => (
										<LogFileCard key={log.name} log={log} folder="root" />
									))}
								</div>
							</ScrollArea>
						</TabsContent>

						<TabsContent value="agents" className="mt-4">
							<ScrollArea className="h-[600px]">
								<div className="space-y-2">
									{filterLogs(agentLogs).map((log) => (
										<LogFileCard key={log.name} log={log} folder="agents" />
									))}
								</div>
							</ScrollArea>
						</TabsContent>
					</Tabs>
				</div>

				<div className="flex-1">
					{selectedLog ? (
						<Card>
							<CardHeader>
								<CardTitle className="flex items-center gap-2">
									<FileText className="w-5 h-5" />
									{selectedLog.filename}
								</CardTitle>
								<CardDescription>
									JSON content viewer with syntax highlighting and collapsible
									sections
								</CardDescription>
							</CardHeader>
							<CardContent>
								{selectedLog.content ? (
									<LogViewer
										data={selectedLog.content}
										filename={selectedLog.filename}
									/>
								) : (
									<div className="p-4 text-center text-muted-foreground">
										No content available
									</div>
								)}
							</CardContent>
						</Card>
					) : (
						<Card>
							<CardContent className="flex items-center justify-center h-[600px]">
								<div className="text-center">
									<FileText className="w-12 h-12 text-muted-foreground mx-auto mb-4" />
									<h3 className="text-lg font-medium mb-2">
										Select a log file to view
									</h3>
									<p className="text-muted-foreground">
										Choose a log file from the sidebar to view its JSON content
									</p>
								</div>
							</CardContent>
						</Card>
					)}

					{loading && (
						<div className="absolute inset-0 bg-background/50 flex items-center justify-center">
							<div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
						</div>
					)}
				</div>
			</div>
		</div>
	);
}
