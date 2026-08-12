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
  return {
    title: `${job.title} — Careers`,
    description: `${job.department} · ${job.location} · ${job.type}. ${job.description.slice(0, 155)}…`,
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
