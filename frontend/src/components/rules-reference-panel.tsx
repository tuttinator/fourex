'use client'

import { useQuery } from '@tanstack/react-query'
import { BookOpen } from 'lucide-react'

import { api, queryKeys } from '@/lib/api'
import type { RulesReference, ResourceBag } from '@/types/game'

import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

function formatCost(cost: ResourceBag): string {
  const parts: string[] = []
  if (cost.food) parts.push(`${cost.food}f`)
  if (cost.wood) parts.push(`${cost.wood}w`)
  if (cost.ore) parts.push(`${cost.ore}o`)
  if (cost.crystal) parts.push(`${cost.crystal}c`)
  if (cost.science) parts.push(`${cost.science}s`)
  return parts.length ? parts.join(' ') : 'free'
}

export function RulesReferencePanel() {
  // Rules are static by schema version — cache forever within a session.
  const { data: rules } = useQuery<RulesReference>({
    queryKey: queryKeys.rulesReference(),
    queryFn: () => api.getRulesReference(),
    staleTime: Infinity,
  })

  if (!rules) {
    return (
      <Card className="rounded-none border-0 border-b">
        <CardHeader className="py-3">
          <CardTitle className="text-sm flex items-center gap-2">
            <BookOpen className="h-4 w-4" />
            Rules reference
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0 pb-3">
          <p className="text-xs text-muted-foreground">Loading…</p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="rounded-none border-0 border-b">
      <CardHeader className="py-3">
        <CardTitle className="text-sm flex items-center gap-2">
          <BookOpen className="h-4 w-4" />
          Rules reference
          <span className="text-[10px] text-muted-foreground ml-auto">
            v{rules.schema_version}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0 pb-3">
        <Accordion type="multiple" className="text-xs">
          <AccordionItem value="units">
            <AccordionTrigger className="py-2 text-xs font-medium">
              Units
            </AccordionTrigger>
            <AccordionContent>
              <table className="w-full">
                <thead>
                  <tr className="text-[10px] text-muted-foreground">
                    <th className="text-left font-medium">Type</th>
                    <th className="text-right font-medium">HP</th>
                    <th className="text-right font-medium">Atk</th>
                    <th className="text-right font-medium">Rng</th>
                    <th className="text-right font-medium">Mv</th>
                    <th className="text-right font-medium">Sight</th>
                    <th className="text-right font-medium">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(rules.units).map(([type, u]) => (
                    <tr key={type}>
                      <td className="capitalize py-0.5">{type}</td>
                      <td className="text-right">{u.hp}</td>
                      <td className="text-right">{u.attack}</td>
                      <td className="text-right">{u.attack_range}</td>
                      <td className="text-right">{u.moves}</td>
                      <td className="text-right">{u.sight}</td>
                      <td className="text-right">{formatCost(u.cost)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="buildings">
            <AccordionTrigger className="py-2 text-xs font-medium">
              Buildings
            </AccordionTrigger>
            <AccordionContent>
              <ul className="space-y-1">
                {Object.entries(rules.buildings).map(([type, b]) => (
                  <li key={type}>
                    <div className="flex justify-between gap-2">
                      <span className="capitalize font-medium">{type}</span>
                      <span className="text-muted-foreground">
                        {formatCost(b.cost)}
                      </span>
                    </div>
                    <div className="text-muted-foreground">{b.effect}</div>
                  </li>
                ))}
              </ul>
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="improvements">
            <AccordionTrigger className="py-2 text-xs font-medium">
              Improvements
            </AccordionTrigger>
            <AccordionContent>
              <ul className="space-y-1">
                {Object.entries(rules.improvements).map(([type, imp]) => (
                  <li key={type}>
                    <div className="flex justify-between gap-2">
                      <span className="capitalize font-medium">
                        {type.replace('_', ' ')}
                      </span>
                      <span className="text-muted-foreground">
                        {formatCost(imp.cost)}
                      </span>
                    </div>
                    <div className="text-muted-foreground">{imp.effect}</div>
                  </li>
                ))}
              </ul>
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="terrain">
            <AccordionTrigger className="py-2 text-xs font-medium">
              Terrain
            </AccordionTrigger>
            <AccordionContent>
              <ul className="space-y-0.5">
                {Object.entries(rules.terrain).map(([type, t]) => (
                  <li key={type} className="flex justify-between">
                    <span className="capitalize">{type}</span>
                    <span className="text-muted-foreground">
                      {t.passable
                        ? `entry cost ${t.entry_cost}`
                        : 'impassable'}
                    </span>
                  </li>
                ))}
              </ul>
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="combat">
            <AccordionTrigger className="py-2 text-xs font-medium">
              Combat
            </AccordionTrigger>
            <AccordionContent className="space-y-1">
              <p>
                <span className="font-medium">Damage: </span>
                <code className="text-[10px]">
                  {rules.combat.damage_formula}
                </code>
              </p>
              <p>
                <span className="font-medium">Counter: </span>
                <code className="text-[10px]">
                  {rules.combat.counter_attack.formula}
                </code>{' '}
                <span className="text-muted-foreground">
                  (excl.{' '}
                  {rules.combat.counter_attack.excluded_units.join(', ')})
                </span>
              </p>
              <p>
                <span className="font-medium">City defence: </span>
                +{Math.round(
                  rules.combat.fortification.city_defence_bonus * 100,
                )}
                % fortification on friendly city tile
              </p>
              <p>
                <span className="font-medium">Soldier vs city: </span>
                ×{rules.combat.city_attack.soldier_bonus_multiplier}
              </p>
              <p>
                <span className="font-medium">Walls counter-fire: </span>
                {rules.combat.city_counter_fire.damage} dmg
              </p>
            </AccordionContent>
          </AccordionItem>

          <AccordionItem value="stacking">
            <AccordionTrigger className="py-2 text-xs font-medium">
              Stacking & orders
            </AccordionTrigger>
            <AccordionContent className="space-y-1">
              <p>
                <span className="font-medium">Stack cap: </span>
                {rules.stacking.cap_per_tile} units/tile
              </p>
              <p className="text-muted-foreground">{rules.stacking.notes}</p>
              <p className="font-medium pt-1">
                Order cancellation triggers:
              </p>
              <ul className="list-disc pl-4 text-muted-foreground">
                {rules.orders.cancellation_conditions.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </AccordionContent>
          </AccordionItem>
        </Accordion>
      </CardContent>
    </Card>
  )
}
