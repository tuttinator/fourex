'use client'

import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import type { PromptAccordionProps, PromptLogEntry } from '@/types/game'
import { formatTokenCount } from '@/lib/api'
import { Brain, Clock, MessageSquare, Zap, Cpu, ChevronDown, ChevronUp } from 'lucide-react'

const TEXT_PREVIEW_LENGTH = 500

function ExpandableText({ text, label }: { text: string; label: string }) {
  const [expanded, setExpanded] = useState(false)
  const needsTruncation = text.length > TEXT_PREVIEW_LENGTH

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <div className="text-xs font-medium text-muted-foreground">{label}:</div>
        {needsTruncation && (
          <Button
            variant="ghost"
            size="sm"
            className="h-5 px-1 text-xs"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? (
              <>
                <ChevronUp className="h-3 w-3 mr-1" />
                Collapse
              </>
            ) : (
              <>
                <ChevronDown className="h-3 w-3 mr-1" />
                Expand
              </>
            )}
          </Button>
        )}
      </div>
      <div
        className={`text-xs bg-background rounded p-2 border overflow-y-auto ${
          expanded ? 'max-h-96' : 'max-h-32'
        }`}
      >
        <pre className="whitespace-pre-wrap font-mono">
          {!expanded && needsTruncation
            ? `${text.substring(0, TEXT_PREVIEW_LENGTH)}...`
            : text}
        </pre>
      </div>
    </div>
  )
}

function PromptEntry({ prompt, index }: { prompt: PromptLogEntry; index: number }) {
  return (
    <div className="border rounded-lg p-3 bg-muted/50">
      {/* Prompt Header */}
      <div className="flex items-center justify-between mb-2">
        <Badge variant="outline" className="text-xs">
          Prompt #{index + 1}
        </Badge>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {(prompt.llm_provider || prompt.llm_model) && (
            <span className="flex items-center gap-1">
              <Cpu className="h-3 w-3" />
              {[prompt.llm_provider, prompt.llm_model].filter(Boolean).join(' / ')}
            </span>
          )}
          <span>
            {prompt.tokens_in}&rarr;{prompt.tokens_out}
          </span>
          <span>{prompt.latency_ms}ms</span>
        </div>
      </div>

      {/* Prompt Content */}
      <div className="space-y-2">
        <ExpandableText text={prompt.prompt} label="Prompt" />
        <ExpandableText text={prompt.response} label="Response" />
      </div>

      {/* Token Analysis */}
      <div className="mt-2 pt-2 border-t">
        <div className="grid grid-cols-4 gap-2 text-xs">
          <div className="text-center">
            <div className="text-muted-foreground">Input</div>
            <div className="font-mono">{formatTokenCount(prompt.tokens_in)}</div>
          </div>
          <div className="text-center">
            <div className="text-muted-foreground">Output</div>
            <div className="font-mono">{formatTokenCount(prompt.tokens_out)}</div>
          </div>
          <div className="text-center">
            <div className="text-muted-foreground">Latency</div>
            <div className="font-mono">{prompt.latency_ms}ms</div>
          </div>
          <div className="text-center">
            <div className="text-muted-foreground">Model</div>
            <div className="font-mono truncate" title={prompt.llm_model ?? 'unknown'}>
              {prompt.llm_model ?? 'n/a'}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export function PromptAccordion({ prompts, players, selectedTurn }: PromptAccordionProps) {
  const playerPrompts = players
    .map((player) => ({
      player,
      prompts: prompts.filter((p) => p.player_id === player),
    }))
    .filter((p) => p.prompts.length > 0)

  if (prompts.length === 0) {
    return (
      <Card className="h-full">
        <CardHeader>
          <CardTitle className="text-sm">LLM Prompts</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-center h-32 text-muted-foreground">
            <div className="text-center">
              <MessageSquare className="h-8 w-8 mx-auto mb-2 opacity-50" />
              <p className="text-sm">No prompts for turn {selectedTurn}</p>
            </div>
          </div>
        </CardContent>
      </Card>
    )
  }

  const totalTokens = prompts.reduce((sum, p) => sum + p.tokens_in + p.tokens_out, 0)
  const avgLatency = prompts.reduce((sum, p) => sum + p.latency_ms, 0) / prompts.length
  const providers = Array.from(new Set(prompts.map((p) => p.llm_provider).filter(Boolean)))

  return (
    <Card className="h-full flex flex-col">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm">LLM Prompts</CardTitle>
          <Badge variant="secondary">{prompts.length}</Badge>
        </div>

        {/* Summary Stats */}
        <div className="grid grid-cols-3 gap-2 mt-2">
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <Zap className="h-3 w-3" />
            <span>{formatTokenCount(totalTokens)} tokens</span>
          </div>
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <Clock className="h-3 w-3" />
            <span>{Math.round(avgLatency)}ms avg</span>
          </div>
          {providers.length > 0 && (
            <div className="flex items-center gap-1 text-xs text-muted-foreground">
              <Cpu className="h-3 w-3" />
              <span>{providers.join(', ')}</span>
            </div>
          )}
        </div>
      </CardHeader>

      <CardContent className="flex-1 p-0">
        <ScrollArea className="h-full">
          <div className="px-4 pb-4">
            <Accordion type="multiple" className="w-full">
              {playerPrompts.map(({ player, prompts: playerPromptList }) => (
                <AccordionItem key={player} value={player}>
                  <AccordionTrigger className="text-sm">
                    <div className="flex items-center justify-between w-full mr-4">
                      <div className="flex items-center gap-2">
                        <Brain className="h-4 w-4" />
                        <span>{player}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant="outline" className="text-xs">
                          {playerPromptList.length}
                        </Badge>
                        <span className="text-xs text-muted-foreground">
                          {formatTokenCount(
                            playerPromptList.reduce(
                              (sum, p) => sum + p.tokens_in + p.tokens_out,
                              0,
                            ),
                          )}
                        </span>
                      </div>
                    </div>
                  </AccordionTrigger>
                  <AccordionContent>
                    <div className="space-y-3">
                      {playerPromptList.map((prompt, idx) => (
                        <PromptEntry key={idx} prompt={prompt} index={idx} />
                      ))}
                    </div>
                  </AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  )
}
