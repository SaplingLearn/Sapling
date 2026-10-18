import type { Metadata } from 'next';
import CareersList from './CareersList';

// Server wrapper so the page can export metadata (#171); the interactive
// expanding job list stays a client child (CareersList).
export const metadata: Metadata = {
  title: 'Careers',
  description:
    "The small team building Sapling — AI-powered study tools that help students learn better. No open roles at the moment; get in touch and tell us what you'd build.",
  alternates: { canonical: '/careers' },
};

export default function CareersPage() {
  return <CareersList />;
}
