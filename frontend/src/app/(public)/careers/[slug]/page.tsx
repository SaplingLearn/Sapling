import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { JOBS } from '../jobs';
import ApplyForm from './ApplyForm';

export function generateStaticParams() {
  return JOBS.map(job => ({ slug: job.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const job = JOBS.find(j => j.slug === slug);
  if (!job) return { title: 'Role not found' };
  // The ellipsis is conditional: appended unconditionally it claimed every
  // short description was truncated, so a 90-character role blurb read as a
  // cut-off fragment in search results and link previews.
  const blurb =
    job.description.length > 155 ? `${job.description.slice(0, 155)}…` : job.description;
  return {
    title: `${job.title} — Careers`,
    description: `${job.department} · ${job.location} · ${job.type}. ${blurb}`,
    alternates: { canonical: `/careers/${job.slug}` },
  };
}

export default async function ApplyPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const job = JOBS.find(j => j.slug === slug);
  // A real 404, not a 200 with fallback UI (#187) — crawlers were indexing
  // the soft-404 thin page.
  if (!job) notFound();
  return <ApplyForm job={job} />;
}
