import { useState, useEffect } from 'react'
import { ChevronRight, ChevronDown, Braces, List, Quote, Hash, CheckCircle2, XCircle, Plus, Minus } from 'lucide-react'
import { cn } from '@/lib/utils'

type JsonValue = string | number | boolean | null | JsonArray | JsonObject
interface JsonArray extends Array<JsonValue> {}
interface JsonObject { [key: string]: JsonValue }

interface JsonTreeNodeProps {
  data: JsonValue
  keyName?: string
  level?: number
  isLast?: boolean
  expandedState: Set<string>
  setExpandedState: React.Dispatch<React.SetStateAction<Set<string>>>
  globalExpand?: boolean | null
  globalCollapse?: boolean | null
}

function getValueIcon(value: JsonValue) {
  if (value === null) return <XCircle className="h-3.5 w-3.5 text-muted-foreground" />
  if (typeof value === 'boolean') return <CheckCircle2 className="h-3.5 w-3.5 text-blue-500" />
  if (typeof value === 'number') return <Hash className="h-3.5 w-3.5 text-green-500" />
  if (typeof value === 'string') return <Quote className="h-3.5 w-3.5 text-orange-500" />
  if (Array.isArray(value)) return <List className="h-3.5 w-3.5 text-purple-500" />
  if (typeof value === 'object') return <Braces className="h-3.5 w-3.5 text-yellow-500" />
  return null
}

function getValueClass(value: JsonValue) {
  if (value === null) return 'text-muted-foreground'
  if (typeof value === 'boolean') return 'text-blue-500'
  if (typeof value === 'number') return 'text-green-500'
  if (typeof value === 'string') return 'text-orange-500'
  return ''
}

function formatValue(value: JsonValue): string {
  if (value === null) return 'null'
  if (typeof value === 'string') return `"${value}"`
  return String(value)
}

function generatePath(keyName: string | undefined, parentPath: string): string {
  return parentPath ? `${parentPath}.${keyName || ''}` : (keyName || '')
}

interface TreeNodeData {
  path: string
  expanded: boolean
}

function JsonTreeNode({ data, keyName, level = 0, isLast = false, expandedState, setExpandedState, globalExpand, globalCollapse }: JsonTreeNodeProps) {
  const path = generatePath(keyName, '')
  const [localExpanded, setLocalExpanded] = useState(() => expandedState.has(path))
  const isObject = typeof data === 'object' && data !== null
  const isArray = Array.isArray(data)
  const isEmpty = isObject && Object.keys(data).length === 0
  const indent = level * 16

  // Sync local state with expanded state
  useEffect(() => {
    setLocalExpanded(expandedState.has(path))
  }, [expandedState, path])

  // Handle global expand/collapse
  useEffect(() => {
    if (globalExpand === true && isObject && !isEmpty) {
      setExpandedState(prev => new Set(prev).add(path))
      setLocalExpanded(true)
    } else if (globalCollapse === true && isObject && !isEmpty) {
      setExpandedState(prev => {
        const next = new Set(prev)
        next.delete(path)
        return next
      })
      setLocalExpanded(false)
    }
  }, [globalExpand, globalCollapse, isObject, isEmpty, path, setExpandedState])

  const handleClick = () => {
    if (isObject && !isEmpty) {
      setLocalExpanded(!localExpanded)
      setExpandedState(prev => {
        const next = new Set(prev)
        if (localExpanded) {
          next.delete(path)
        } else {
          next.add(path)
        }
        return next
      })
    }
  }

  if (!isObject) {
    return (
      <div className="flex items-center gap-1.5 py-0.5" style={{ paddingLeft: `${indent}px` }}>
        {keyName && (
          <>
            <span className="text-blue-600 font-medium">{keyName}</span>
            <span className="text-muted-foreground">:</span>
          </>
        )}
        <span className={cn('font-mono text-xs', getValueClass(data))}>
          {formatValue(data)}
        </span>
        {!isLast && <span className="text-muted-foreground">,</span>}
      </div>
    )
  }

  const keys = Object.keys(data)
  const length = keys.length

  return (
    <div>
      <div
        className={cn(
          'flex items-center gap-1.5 py-0.5 cursor-pointer hover:bg-muted/50 rounded',
          isEmpty && 'cursor-default'
        )}
        style={{ paddingLeft: `${indent}px` }}
        onClick={handleClick}
      >
        {!isEmpty && (
          <span className="shrink-0">
            {localExpanded ? (
              <ChevronDown className="h-3 w-3 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-3 w-3 text-muted-foreground" />
            )}
          </span>
        )}
        {keyName && (
          <>
            <span className="text-blue-600 font-medium">{keyName}</span>
            <span className="text-muted-foreground">:</span>
          </>
        )}
        <span className="text-muted-foreground font-mono text-xs">
          {isArray ? '[' : '{'}{!isEmpty && !localExpanded && ` ...${length} items`}{!isEmpty && localExpanded && ''}{isArray ? ']' : '}'}
        </span>
        {!isLast && <span className="text-muted-foreground">,</span>}
      </div>
      {localExpanded && !isEmpty && (
        <div>
          {keys.map((key, index) => (
            <JsonTreeNode
              key={key}
              data={data[key]}
              keyName={isArray ? undefined : key}
              level={level + 1}
              isLast={index === length - 1}
              expandedState={expandedState}
              setExpandedState={setExpandedState}
              globalExpand={globalExpand}
              globalCollapse={globalCollapse}
            />
          ))}
        </div>
      )}
    </div>
  )
}

interface JsonViewerProps {
  data: JsonValue | null
  loading?: boolean
  error?: string
  onReload?: () => void
  className?: string
  showControls?: boolean
}

export function JsonViewer({ data, loading, error, onReload, className, showControls = true }: JsonViewerProps) {
  const [expandedState, setExpandedState] = useState<Set<string>>(new Set())
  const [globalExpand, setGlobalExpand] = useState<boolean | null>(null)
  const [globalCollapse, setGlobalCollapse] = useState<boolean | null>(null)

  const handleExpandAll = () => {
    setGlobalExpand(true)
    setGlobalCollapse(null)
    // Reset after animation
    setTimeout(() => setGlobalExpand(null), 100)
  }

  const handleCollapseAll = () => {
    setGlobalCollapse(true)
    setGlobalExpand(null)
    // Reset after animation
    setTimeout(() => setGlobalCollapse(null), 100)
  }

  if (loading) {
    return (
      <div className={cn('flex items-center justify-center py-8', className)}>
        <p className="text-muted-foreground text-sm">Loading…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className={cn('p-4', className)}>
        <p className="text-destructive text-sm">{error}</p>
      </div>
    )
  }

  if (!data) {
    return (
      <div className={cn('flex items-center justify-center py-8', className)}>
        <p className="text-muted-foreground text-sm">No data available</p>
      </div>
    )
  }

  return (
    <div className={cn('space-y-2', className)}>
      {showControls && (
        <div className="flex items-center gap-2 pb-2 border-b border-border/50">
          <span className="text-xs text-muted-foreground">Tree controls:</span>
          <button
            onClick={handleExpandAll}
            className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded hover:bg-muted transition-colors"
          >
            <Plus className="h-3 w-3" />
            Expand all
          </button>
          <button
            onClick={handleCollapseAll}
            className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded hover:bg-muted transition-colors"
          >
            <Minus className="h-3 w-3" />
            Collapse all
          </button>
        </div>
      )}
      <div className="font-mono text-xs">
        <JsonTreeNode
          data={data}
          expandedState={expandedState}
          setExpandedState={setExpandedState}
          globalExpand={globalExpand}
          globalCollapse={globalCollapse}
        />
      </div>
    </div>
  )
}
