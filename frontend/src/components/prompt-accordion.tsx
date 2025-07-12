'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { ScrollArea } from '@/components/ui/scroll-area'
import { 
  Accordion, 
  AccordionContent, 
  AccordionItem, 
  AccordionTrigger 
} from '@/components/ui/accordion'
import type { PromptAccordionProps } from '@/types/game'
import { formatTokenCount } from '@/lib/api'
import { Brain, Clock, MessageSquare, Zap } from 'lucide-react'

export function PromptAccordion({ prompts, players, selectedTurn }: PromptAccordionProps) {
  const playerPrompts = players.map(player => ({
    player,
    prompts: prompts.filter(p => p.player === player)
  })).filter(p => p.prompts.length > 0)

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

  return (
    <Card className="h-full flex flex-col">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm">LLM Prompts</CardTitle>
          <Badge variant="secondary">{prompts.length}</Badge>
        </div>
        
        {/* Summary Stats */}
        <div className="grid grid-cols-2 gap-2 mt-2">
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <Zap className="h-3 w-3" />
            <span>{formatTokenCount(totalTokens)} tokens</span>
          </div>
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <Clock className="h-3 w-3" />
            <span>{Math.round(avgLatency)}ms avg</span>
          </div>
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
                            playerPromptList.reduce((sum, p) => sum + p.tokens_in + p.tokens_out, 0)
                          )}
                        </span>
                      </div>
                    </div>
                  </AccordionTrigger>
                  <AccordionContent>
                    <div className="space-y-3">
                      {playerPromptList.map((prompt, idx) => (
                        <div key={idx} className="border rounded-lg p-3 bg-muted/50">
                          {/* Prompt Header */}
                          <div className="flex items-center justify-between mb-2">
                            <Badge variant="outline" className="text-xs">
                              Prompt #{idx + 1}
                            </Badge>
                            <div className="flex items-center gap-2 text-xs text-muted-foreground">
                              <span>{prompt.tokens_in}→{prompt.tokens_out}</span>
                              <span>{prompt.latency_ms}ms</span>
                            </div>
                          </div>
                          
                          {/* Prompt Content */}
                          <div className="space-y-2">
                            <div>
                              <div className="text-xs font-medium text-muted-foreground mb-1">
                                Prompt:
                              </div>
                              <div className="text-xs bg-background rounded p-2 border max-h-32 overflow-y-auto">
                                <pre className="whitespace-pre-wrap font-mono">
                                  {prompt.prompt.length > 500 
                                    ? `${prompt.prompt.substring(0, 500)}...` 
                                    : prompt.prompt
                                  }
                                </pre>
                              </div>
                            </div>
                            
                            <div>
                              <div className="text-xs font-medium text-muted-foreground mb-1">
                                Response:
                              </div>
                              <div className="text-xs bg-background rounded p-2 border max-h-32 overflow-y-auto">
                                <pre className="whitespace-pre-wrap font-mono">
                                  {prompt.response.length > 500 
                                    ? `${prompt.response.substring(0, 500)}...` 
                                    : prompt.response
                                  }
                                </pre>
                              </div>
                            </div>
                          </div>
                          
                          {/* Token Analysis */}
                          <div className="mt-2 pt-2 border-t">
                            <div className="grid grid-cols-3 gap-2 text-xs">
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
                            </div>
                          </div>
                        </div>
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