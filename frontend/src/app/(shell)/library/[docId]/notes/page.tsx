import { Notes } from "@/components/notes/Notes";

/**
 * One document's editable notes. The id comes from the route, so a link into
 * a document's notes is shareable and survives a reload.
 */
export default async function NotesPage({
  params,
}: {
  params: Promise<{ docId: string }>;
}) {
  const { docId } = await params;
  return <Notes documentId={docId} />;
}
