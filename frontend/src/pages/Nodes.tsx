import { useEffect, useState } from 'react'
import { nodes as nodesApi, settings } from '../api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'

type Node = { id: number; source: string; raw_link: string; name: string; latency_ms: number | null; real_latency_ms: number | null; last_check: string | null }

export default function Nodes() {
  const [list, setList] = useState<Node[]>([])
  const [selectedRaw, setSelectedRaw] = useState('')
  const [loading, setLoading] = useState(true)
  const [selecting, setSelecting] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null)

  function load() {
    Promise.all([nodesApi.list(), settings.get()]).then(([nodesRes, setRes]) => {
      setList(nodesRes.nodes)
      setSelectedRaw(setRes.selected_node_raw || '')
    }).finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  async function handleSelect(raw_link: string) {
    setSelecting(raw_link)
    setMessage(null)
    try {
      await nodesApi.select(raw_link)
      setSelectedRaw(raw_link)
      setMessage('Node selected and core restarted.')
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Failed')
    } finally {
      setSelecting(null)
    }
  }

  function askDelete(id: number) {
    setConfirmDelete(id)
  }

  function cancelDelete() {
    setConfirmDelete(null)
  }

  async function handleDelete(id: number) {
    setDeleting(id)
    setMessage(null)
    setConfirmDelete(null)
    try {
      await nodesApi.delete(id)
      setMessage('Node deleted.')
      await Promise.all([nodesApi.list(), settings.get()]).then(([nodesRes, setRes]) => {
        setList(nodesRes.nodes)
        setSelectedRaw(setRes.selected_node_raw || '')
      })
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Failed to delete')
    } finally {
      setDeleting(null)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <p className="text-muted-foreground">Loading…</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Nodes</h1>
        <p className="text-muted-foreground">
          Best node by latency is auto-selected every 1 min. You can manually select a node below.
        </p>
      </div>

      {message && (
        <Alert variant="default">
          <AlertDescription>{message}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Node list</CardTitle>
          <CardDescription>Select a node to use or delete it</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="rounded-md border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Latency (ms)</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead className="w-[180px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={4} className="text-center text-muted-foreground">
                      No nodes. Add a subscription URL and refresh.
                    </TableCell>
                  </TableRow>
                )}
                {list.map((n) => (
                  <TableRow key={n.id} className={cn(selectedRaw === n.raw_link && 'bg-muted/50')}>
                    <TableCell className="font-mono text-sm max-w-[200px] truncate">
                      {n.name || n.raw_link.slice(0, 40)}
                    </TableCell>
                    <TableCell>{n.real_latency_ms != null ? n.real_latency_ms : n.latency_ms != null ? `${n.latency_ms} (TCP)` : '—'}</TableCell>
                    <TableCell>{n.source}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => handleSelect(n.raw_link)}
                          disabled={selecting !== null}
                        >
                          {selecting === n.raw_link ? '…' : 'Use'}
                        </Button>
                        {confirmDelete === n.id ? (
                          <>
                            <span className="text-sm text-muted-foreground">Delete?</span>
                            <Button
                              size="sm"
                              variant="destructive"
                              onClick={() => handleDelete(n.id)}
                              disabled={deleting !== null}
                            >
                              Yes
                            </Button>
                            <Button size="sm" variant="ghost" onClick={cancelDelete}>
                              No
                            </Button>
                          </>
                        ) : (
                          <Button
                            size="sm"
                            variant="destructive"
                            onClick={() => askDelete(n.id)}
                            disabled={deleting !== null}
                            title="Delete node"
                          >
                            Delete
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
