import { JOBS } from '../jobs';
import ApplyForm from './ApplyForm';

export function generateStaticParams() {
  return JOBS.map(job => ({ slug: job.slug }));
}

export default async function ApplyPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const job = JOBS.find(j => j.slug === slug) ?? null;
  return <ApplyForm job={job} />;
}
