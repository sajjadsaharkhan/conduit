import { useEffect, useState } from 'react'
import { domains as domainsApi } from '../api'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Alert, AlertDescription } from '@/components/ui/alert'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

type Domain = { id: number; type: string; value: string }
const DOMAIN_TYPES = [
  { value: 'exact', label: 'Exact (domain exact match)' },
  { value: 'domain_suffix', label: 'Domain + all subdomains' },
  { value: 'contains', label: 'Contains (keyword → domains containing)' },
  { value: 'regex', label: 'Regex (xray/sing-box valid)' },
] as const
const TYPE_LABELS: Record<string, string> = {
  exact: 'Exact',
  domain_suffix: 'Domain + subdomains',
  contains: 'Contains',
  regex: 'Regex',
  domain: 'Domain',
  suffix: 'Suffix',
  keyword: 'Keyword',
}

export default function Domains() {
  const [list, setList] = useState<Domain[]>([])
  const [loading, setLoading] = useState(true)
  const [addType, setAddType] = useState<string>(DOMAIN_TYPES[0].value)
  const [addValue, setAddValue] = useState('')
  const [adding, setAdding] = useState(false)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [deleteModal, setDeleteModal] = useState<{ id: number; value: string } | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [importText, setImportText] = useState('')
  const [importSubmitting, setImportSubmitting] = useState(false)

  function load() {
    domainsApi.list().then((d) => setList(d.domains)).finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [])

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    if (!addValue.trim()) return
    setAdding(true)
    setMessage(null)
    try {
      await domainsApi.add(addType as string, addValue.trim())
      setAddValue('')
      load()
      setMessage('Domain added.')
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Failed')
    } finally {
      setAdding(false)
    }
  }

  async function handleDelete(id: number) {
    setDeleteModal(null)
    setDeleting(id)
    try {
      await domainsApi.delete(id)
      load()
    } finally {
      setDeleting(null)
    }
  }

  async function handleBulkImport(e: React.FormEvent) {
    e.preventDefault()
    if (!importText.trim()) return
    setImportSubmitting(true)
    setMessage(null)
    try {
      const res = await domainsApi.bulk(importText)
      setMessage(res.message ?? `Added ${res.added} domain rule(s).`)
      setImportOpen(false)
      setImportText('')
      load()
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Import failed')
    } finally {
      setImportSubmitting(false)
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
        <h1 className="text-3xl font-bold tracking-tight">Proxy domains</h1>
        <p className="text-muted-foreground">
          Only traffic to these domains uses the proxy. All other traffic goes direct.
        </p>
      </div>

      {message && (
        <Alert variant={message.startsWith('Domain added') ? 'success' : 'destructive'}>
          <AlertDescription>{message}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Add domain</CardTitle>
          <CardDescription>Exact match, domain + subdomains, contains keyword, or regex</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleAdd} className="flex flex-wrap items-end gap-4">
            <div className="space-y-2">
              <Label>Type</Label>
              <Select value={addType} onValueChange={setAddType}>
                <SelectTrigger className="w-[240px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DOMAIN_TYPES.map((t) => (
                    <SelectItem key={t.value} value={t.value}>
                      {t.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex-1 min-w-[200px] space-y-2">
              <Label htmlFor="domain-value">Value</Label>
              <Input
                id="domain-value"
                type="text"
                value={addValue}
                onChange={(e) => setAddValue(e.target.value)}
                placeholder={addType === 'regex' ? 'e.g. \\.google\\.com$' : 'e.g. google.com or keyword'}
              />
            </div>
            <Button type="submit" disabled={adding || !addValue.trim()}>
              {adding ? '…' : 'Add'}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-start justify-between space-y-0 pb-2">
          <div>
            <CardTitle>Domain list</CardTitle>
            <CardDescription>Rules that use the proxy</CardDescription>
          </div>
          <Button variant="secondary" size="sm" onClick={() => setImportOpen(true)}>
            Import list
          </Button>
        </CardHeader>
        <CardContent>
          <div className="rounded-md border border-border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Type</TableHead>
                  <TableHead>Value</TableHead>
                  <TableHead className="w-[100px]">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={3} className="text-center text-muted-foreground">
                      No domains. Add one above or import a list.
                    </TableCell>
                  </TableRow>
                )}
                {list.map((d) => (
                  <TableRow key={d.id}>
                    <TableCell className="font-medium">{TYPE_LABELS[d.type] ?? d.type}</TableCell>
                    <TableCell className="font-mono text-sm">{d.value}</TableCell>
                    <TableCell>
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => setDeleteModal({ id: d.id, value: d.value })}
                        disabled={deleting !== null}
                      >
                        {deleting === d.id ? '…' : 'Remove'}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Delete confirm modal */}
      <Dialog open={!!deleteModal} onOpenChange={(open) => !open && setDeleteModal(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove domain?</DialogTitle>
            <DialogDescription>
              This will remove the rule &quot;{deleteModal?.value}&quot;. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteModal(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteModal && handleDelete(deleteModal.id)}
              disabled={deleting !== null}
            >
              {deleting !== null ? '…' : 'Remove'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Bulk import modal */}
      <Dialog open={importOpen} onOpenChange={setImportOpen}>
        <DialogContent className="max-w-2xl max-h-[90vh] flex flex-col">
          <DialogHeader>
            <DialogTitle>Import domain list</DialogTitle>
            <DialogDescription>
              Paste one entry per line. Plain lines (e.g. localhost, meet.google.com) → exact match. Lines starting with *. (e.g. *.google.com) → domain + subdomains. Lines like *keyword* → contains that keyword. Empty lines and # comments are ignored.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleBulkImport} className="flex flex-col flex-1 min-h-0">
            <textarea
              className="flex-1 min-h-[280px] w-full rounded-md border border-border bg-background px-3 py-2 text-sm font-mono resize-y"
              value={importText}
              onChange={(e) => setImportText(e.target.value)}
              placeholder={'127.0.0.1\nlocalhost\nmeet.google.com\n*.google.com\n*digikala*\n…'}
              spellCheck={false}
            />
            <DialogFooter className="mt-4">
              <Button type="button" variant="outline" onClick={() => setImportOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={importSubmitting || !importText.trim()}>
                {importSubmitting ? 'Importing…' : 'Import'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
