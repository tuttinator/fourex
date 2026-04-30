/**
 * Phase 5 (map system overhaul): client component for the /maps list
 * page. Adds edit + delete row actions on top of the read-only Phase 4
 * table; deletion goes through a confirm dialog before calling the
 * Phase 4 DELETE endpoint via the BFF proxy.
 */
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { useToast } from "@/hooks/use-toast";
import { api, ApiError } from "@/lib/api";
import type { SavedMapSummary } from "@/types/game";

interface MapsListClientProps {
  maps: SavedMapSummary[];
}

function formatDate(value: string): string {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString();
}

export function MapsListClient({ maps }: MapsListClientProps) {
  const router = useRouter();
  const { toast } = useToast();
  const [pendingDelete, setPendingDelete] = useState<SavedMapSummary | null>(
    null,
  );
  const [deleting, setDeleting] = useState(false);

  const handleConfirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await api.deleteSavedMap(pendingDelete.id);
      toast({ title: "Map deleted" });
      setPendingDelete(null);
      router.refresh();
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : error instanceof Error
            ? error.message
            : "Delete failed";
      toast({
        title: "Delete failed",
        description: message,
        variant: "destructive",
      });
    } finally {
      setDeleting(false);
    }
  };

  if (maps.length === 0) {
    return (
      <div
        className="mt-6 flex flex-col items-start gap-3"
        data-testid="maps-empty"
      >
        <p className="text-sm text-ink-muted">
          No saved maps yet. Create the first one with the editor.
        </p>
        <Button asChild>
          <Link href="/maps/new" data-testid="maps-new-link">
            New map
          </Link>
        </Button>
      </div>
    );
  }

  return (
    <>
      <table className="mt-6 w-full text-sm" data-testid="maps-list">
        <thead>
          <tr className="border-b text-left text-xs uppercase text-ink-muted">
            <th className="py-2 pr-4">Name</th>
            <th className="py-2 pr-4">Dimensions</th>
            <th className="py-2 pr-4">Spawn zones</th>
            <th className="py-2 pr-4">Author</th>
            <th className="py-2 pr-4">Updated</th>
            <th className="py-2 pr-4 text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          {maps.map((m) => (
            <tr key={m.id} className="border-b" data-testid={`maps-row-${m.id}`}>
              <td className="py-2 pr-4 font-medium text-ink">{m.name}</td>
              <td className="py-2 pr-4 text-ink-muted">
                {m.width} × {m.height}
              </td>
              <td className="py-2 pr-4 text-ink-muted">{m.spawn_zone_count}</td>
              <td className="py-2 pr-4 text-ink-muted">
                {m.creator_email ?? "—"}
              </td>
              <td className="py-2 pr-4 text-ink-muted">
                {formatDate(m.updated_at)}
              </td>
              <td className="py-2 pr-4 text-right">
                <div className="flex justify-end gap-2">
                  <Button asChild variant="outline" size="sm">
                    <Link
                      href={`/maps/${m.id}/edit`}
                      data-testid={`maps-edit-${m.id}`}
                    >
                      Edit
                    </Link>
                  </Button>
                  <Button
                    type="button"
                    variant="destructive"
                    size="sm"
                    onClick={() => setPendingDelete(m)}
                    data-testid={`maps-delete-${m.id}`}
                  >
                    Delete
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <AlertDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this map?</AlertDialogTitle>
            <AlertDialogDescription>
              {pendingDelete
                ? `“${pendingDelete.name}” will be permanently removed. Existing games that already started on this map are not affected.`
                : null}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmDelete}
              disabled={deleting}
              data-testid="maps-delete-confirm"
            >
              {deleting ? "Deleting…" : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
