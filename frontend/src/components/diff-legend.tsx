'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'

export function DiffLegend() {
  return (
    <Card className="w-48">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">Diff Legend</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 bg-green-500/30 border-2 border-green-500 rounded"></div>
          <span className="text-xs">Added</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 bg-red-500/30 border-2 border-red-500 rounded"></div>
          <span className="text-xs">Removed</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 bg-yellow-500/30 border-2 border-yellow-500 rounded"></div>
          <span className="text-xs">Modified</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 bg-blue-500/30 border-2 border-blue-500 rounded"></div>
          <span className="text-xs">Moved</span>
        </div>
        
        <div className="pt-2 border-t">
          <div className="text-xs text-muted-foreground">
            Compare changes between consecutive turns
          </div>
        </div>
      </CardContent>
    </Card>
  )
}