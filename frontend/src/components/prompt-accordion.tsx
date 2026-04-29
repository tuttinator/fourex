'use client'

import { useMemo, useState } from 'react'
import { Brain, ChevronDown, ChevronUp, Cpu, Eye, MessageSquare, Wrench, Zap } from 'lucide-react'

import { Identity } from '@/components/brand/identity'
import { Button } from '@/components/ui/button'
import { Panel } from '@/components/ui/panel'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Tag } from '@/components/ui/tag'
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { formatTokenCount } from '@/lib/api'
import { PLAYER_COLORS, type PromptAccordionProps, type PromptLogEntry } from '@/types/game'

const TEXT_PREVIEW_LENGTH = 500

interface SectionExtract {
  observe: string | null
  tools: string | null
  reasoning: string | null
  action: string | null
}

const SECTION_DEFS: Array<{
  key: keyof SectionExtract
  label: string
  Icon: typeof Eye
}> = [
  { key: 'observe', label: 'observe()', Icon: Eye },
  { key: 'tools', label: 'available tools', Icon: Wrench },
  { key: 'reasoning', label: 'reasoning', Icon: Brain },
  { key: 'action', label: 'action', Icon: Zap },
]

/** Best-effort split of a saved prompt+response into the four prototype
 * sections. Saved snapshots predate this structure, so we look for
 * common headers in the prompt text and fall back to splitting the
 * response between reasoning and action when the LLM returned a clean
 * prefix/suffix pair. Anything missing renders an empty placeholder. */
function extractSections(prompt: PromptLogEntry): SectionExtract {
  const text = prompt.prompt ?? ''
  const response = prompt.response ?? ''

  const grab = (label: RegExp): string | null => {
    const match = text.match(label)
    if (!match) return null
    const start = match.index! + match[0].length
    const remainder = text.slice(start)
    const nextHeader = remainder.search(
      /\n\s*(observe|available\s+tools|reasoning|action)\s*[():\n]/i,
    )
    const slice =
      nextHeader === -1 ? remainder : remainder.slice(0, nextHeader)
    return slice.trim() || null
  }

  const observe = grab(/observe\s*\(\)\s*[:\n]/i)
  const tools = grab(/available\s+tools\s*[:\n]/i)

  let reasoning = grab(/reasoning\s*[:\n]/i)
  let action = grab(/action\s*[:\n]/i)

  if (!reasoning && !action && response) {
    const tagged = response.match(/<think>([\s\S]*?)<\/think>([\s\S]*)/i)
    if (tagged) {
      reasoning = tagged[1].trim() || null
      action = tagged[2].trim() || null
    } else {
      action = response.trim() || null
    }
  }

  return { observe, tools, reasoning, action }
}

function ExpandableText({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false)
  const needsTruncation = text.length > TEXT_PREVIEW_LENGTH
  return (
    <div>
      <div
        className={`overflow-y-auto rounded-md border border-border bg-bg-subtle p-2 ${
          expanded ? 'max-h-96' : 'max-h-32'
        }`}
      >
        <pre className="whitespace-pre-wrap font-mono text-xs text-ink">
          {!expanded && needsTruncation
            ? `${text.substring(0, TEXT_PREVIEW_LENGTH)}…`
            : text}
        </pre>
      </div>
      {needsTruncation && (
        <Button
          variant="ghost"
          size="sm"
          className="mt-1 h-5 px-1 text-xs"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? (
            <>
              <ChevronUp className="mr-1 h-3 w-3" />
              Collapse
            </>
          ) : (
            <>
              <ChevronDown className="mr-1 h-3 w-3" />
              Expand
            </>
          )}
        </Button>
      )}
    </div>
  )
}

function PromptEntry({ prompt, index }: { prompt: PromptLogEntry; index: number }) {
  const sections = useMemo(() => extractSections(prompt), [prompt])
  return (
    <div className="space-y-2 rounded-md border border-border bg-surface p-3">
      <div className="flex items-center justify-between">
        <Tag tone="neutral" mono>
          prompt #{index + 1}
        </Tag>
        <div
          className="flex items-center gap-2 font-mono tabular-nums text-ink-muted"
          style={{ fontSize: 11 }}
        >
          {(prompt.llm_provider || prompt.llm_model) && (
            <span className="flex items-center gap-1">
              <Cpu className="h-3 w-3" />
              {[prompt.llm_provider, prompt.llm_model].filter(Boolean).join(' / ')}
            </span>
          )}
          <span>
            {prompt.tokens_in}→{prompt.tokens_out}
          </span>
          <span>{prompt.latency_ms}ms</span>
        </div>
      </div>
      <div className="space-y-2">
        {SECTION_DEFS.map(({ key, label, Icon }) => {
          const value = sections[key]
          return (
            <div key={key} className="space-y-1">
              <div className="flex items-center gap-1.5">
                <Icon className="h-3 w-3 text-accent" />
                <span
                  className="font-mono uppercase text-accent"
                  style={{ fontSize: 10, letterSpacing: '0.10em' }}
                >
                  {label}
                </span>
              </div>
              {value ? (
                <ExpandableText text={value} />
              ) : (
                <div
                  className="rounded-md border border-dashed border-border bg-bg-subtle/50 p-2 text-ink-muted"
                  style={{ fontSize: 11 }}
                >
                  Not captured for this turn.
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function PromptAccordion({ prompts, players, selectedTurn }: PromptAccordionProps) {
  const playerPrompts = useMemo(
    () =>
      players
        .map((player, idx) => ({
          player,
          color: PLAYER_COLORS[idx % 8] ?? '#888',
          prompts: prompts.filter((p) => p.player_id === player),
        }))
        .filter((p) => p.prompts.length > 0),
    [players, prompts],
  )

  if (prompts.length === 0) {
    return (
      <Panel
        title="Prompt"
        kicker="agent reasoning"
        className="h-full"
      >
        <div className="flex h-32 items-center justify-center text-ink-muted">
          <div className="text-center">
            <MessageSquare className="mx-auto mb-2 h-8 w-8 opacity-50" />
            <p className="text-sm">No prompts captured for turn {selectedTurn}.</p>
          </div>
        </div>
      </Panel>
    )
  }

  const totalTokens = prompts.reduce(
    (sum, p) => sum + p.tokens_in + p.tokens_out,
    0,
  )
  const avgLatency = prompts.reduce((sum, p) => sum + p.latency_ms, 0) / prompts.length

  return (
    <Panel
      title="Prompt"
      kicker={`turn ${selectedTurn} · ${prompts.length} prompts`}
      action={
        <div className="flex items-center gap-1.5">
          <Tag tone="neutral" mono>
            {formatTokenCount(totalTokens)} tok
          </Tag>
          <Tag tone="neutral" mono>
            {Math.round(avgLatency)}ms
          </Tag>
        </div>
      }
      className="flex h-full flex-col"
      padded={false}
    >
      <ScrollArea className="h-full">
        <div className="px-3 py-3">
          <Accordion type="multiple" className="w-full">
            {playerPrompts.map(({ player, color, prompts: playerPromptList }) => (
              <AccordionItem key={player} value={player}>
                <AccordionTrigger>
                  <div className="mr-3 flex w-full items-center justify-between gap-2">
                    <Identity
                      kind="human"
                      name={player}
                      id={player}
                      color={color}
                      size={20}
                    />
                    <div className="flex items-center gap-1.5">
                      <Tag tone="neutral" mono>
                        {playerPromptList.length}
                      </Tag>
                      <span
                        className="font-mono tabular-nums text-ink-muted"
                        style={{ fontSize: 11 }}
                      >
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
                  <div className="space-y-3 pt-2">
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
    </Panel>
  )
}
