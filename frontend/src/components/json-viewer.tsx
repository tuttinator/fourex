"use client";

import { Check, ChevronDown, ChevronRight, Copy } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

interface JsonViewerProps {
	data: unknown;
	className?: string;
}

interface JsonNodeProps {
	value: unknown;
	keyName?: string;
	level?: number;
	isLast?: boolean;
}

export function JsonViewer({ data, className }: JsonViewerProps) {
	const [copied, setCopied] = useState(false);

	const copyToClipboard = async () => {
		try {
			await navigator.clipboard.writeText(JSON.stringify(data, null, 2));
			setCopied(true);
			setTimeout(() => setCopied(false), 2000);
		} catch (error) {
			console.error("Failed to copy to clipboard:", error);
		}
	};

	return (
		<div className={cn("border rounded-md", className)}>
			<div className="flex items-center justify-between p-2 border-b bg-muted/50">
				<span className="text-sm font-medium">JSON Content</span>
				<Button
					variant="ghost"
					size="sm"
					onClick={copyToClipboard}
					className="h-8 px-2"
				>
					{copied ? (
						<Check className="w-4 h-4" />
					) : (
						<Copy className="w-4 h-4" />
					)}
					{copied ? "Copied!" : "Copy"}
				</Button>
			</div>
			<ScrollArea className="h-[500px] p-4">
				<JsonNode value={data} level={0} />
			</ScrollArea>
		</div>
	);
}

function JsonNode({ value, keyName, level = 0, isLast = true }: JsonNodeProps) {
	const [isCollapsed, setIsCollapsed] = useState(level > 2);

	const indent = level * 20;

	if (value === null) {
		return (
			<div style={{ marginLeft: indent }} className="flex items-center">
				{keyName && <span className="text-blue-600 mr-2">"{keyName}":</span>}
				<span className="text-gray-500">null</span>
				{!isLast && <span className="text-gray-400">,</span>}
			</div>
		);
	}

	if (typeof value === "string") {
		return (
			<div style={{ marginLeft: indent }} className="flex items-center">
				{keyName && <span className="text-blue-600 mr-2">"{keyName}":</span>}
				<span className="text-green-600">"{value}"</span>
				{!isLast && <span className="text-gray-400">,</span>}
			</div>
		);
	}

	if (typeof value === "number" || typeof value === "boolean") {
		return (
			<div style={{ marginLeft: indent }} className="flex items-center">
				{keyName && <span className="text-blue-600 mr-2">"{keyName}":</span>}
				<span className="text-purple-600">{String(value)}</span>
				{!isLast && <span className="text-gray-400">,</span>}
			</div>
		);
	}

	if (Array.isArray(value)) {
		const isEmpty = value.length === 0;

		return (
			<div style={{ marginLeft: indent }}>
				<div className="flex items-center">
					{keyName && <span className="text-blue-600 mr-2">"{keyName}":</span>}
					{!isEmpty && (
						<Button
							variant="ghost"
							size="sm"
							onClick={() => setIsCollapsed(!isCollapsed)}
							className="h-auto p-0 mr-1"
						>
							{isCollapsed ? (
								<ChevronRight className="w-4 h-4" />
							) : (
								<ChevronDown className="w-4 h-4" />
							)}
						</Button>
					)}
					<span className="text-gray-400">[</span>
					{isEmpty && <span className="text-gray-400 ml-1">]</span>}
					{!isEmpty && isCollapsed && (
						<span className="text-gray-500 ml-1">...{value.length} items]</span>
					)}
				</div>

				{!isEmpty && !isCollapsed && (
					<>
						{value.map((item, index) => (
							<JsonNode
								key={`array-${level}-${index}-${typeof item}`}
								value={item}
								level={level + 1}
								isLast={index === value.length - 1}
							/>
						))}
						<div style={{ marginLeft: indent }} className="text-gray-400">
							]
						</div>
					</>
				)}
				{!isLast && <span className="text-gray-400">,</span>}
			</div>
		);
	}

	if (typeof value === "object" && value !== null) {
		const entries = Object.entries(value as Record<string, unknown>);
		const isEmpty = entries.length === 0;

		return (
			<div style={{ marginLeft: indent }}>
				<div className="flex items-center">
					{keyName && <span className="text-blue-600 mr-2">"{keyName}":</span>}
					{!isEmpty && (
						<Button
							variant="ghost"
							size="sm"
							onClick={() => setIsCollapsed(!isCollapsed)}
							className="h-auto p-0 mr-1"
						>
							{isCollapsed ? (
								<ChevronRight className="w-4 h-4" />
							) : (
								<ChevronDown className="w-4 h-4" />
							)}
						</Button>
					)}
					<span className="text-gray-400">{"{"}</span>
					{isEmpty && <span className="text-gray-400 ml-1">{"}"}</span>}
					{!isEmpty && isCollapsed && (
						<span className="text-gray-500 ml-1">
							...{entries.length} keys{"}"}
						</span>
					)}
				</div>

				{!isEmpty && !isCollapsed && (
					<>
						{entries.map(([key, val], index) => (
							<JsonNode
								key={key}
								value={val}
								keyName={key}
								level={level + 1}
								isLast={index === entries.length - 1}
							/>
						))}
						<div style={{ marginLeft: indent }} className="text-gray-400">
							{"}"}
						</div>
					</>
				)}
				{!isLast && <span className="text-gray-400">,</span>}
			</div>
		);
	}

	return (
		<div style={{ marginLeft: indent }} className="flex items-center">
			{keyName && <span className="text-blue-600 mr-2">"{keyName}":</span>}
			<span className="text-red-600">{String(value)}</span>
			{!isLast && <span className="text-gray-400">,</span>}
		</div>
	);
}
