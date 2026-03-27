import { JOBS } from '../jobs';
import ApplyForm from './ApplyForm';

export function generateStaticParams() {
  return JOBS.map(job => ({ slug: job.slug }));
}

export default function ApplyPage({ params }: { params: { slug: string } }) {
  const job = JOBS.find(j => j.slug === params.slug) ?? null;
  return <ApplyForm job={job} />;
}
